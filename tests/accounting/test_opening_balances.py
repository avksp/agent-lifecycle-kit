"""P02 journal integration: actual transactions, races, failure/reopen and lineage."""
import copy
import hashlib
import json
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from agent_lifecycle.accounting.closing_resource_recovery import _claim_in_transaction, _reserve_in_transaction
from agent_lifecycle.accounting.contracts import (
    MAX_INTEGER,
    STORAGE_SCHEMA_VERSION,
    BudgetPolicy,
    BudgetScope,
    CloseoutLineage,
    EvidenceRef,
    HistoricalCharge,
    ImportAmendment,
    OpeningBalance,
    OpeningImport,
    PendingImport,
    SourceBaseline,
    canonical,
    digest,
)
from agent_lifecycle.accounting.journal import BASE_STATEMENTS, Journal, JournalUnavailable
from agent_lifecycle.accounting.opening_balances import compile_opening

from .test_journal import PROOF, operation, receipt
from .test_normalization import atom, observation, profile
from contextlib import closing


def import_data(scope='run', *, historical=(), pending=(), spent=0, protected=None,
                cumulative=False, unknown=(), partials=None):
    p=profile(scope,cumulative)
    policy=BudgetPolicy('policy',1,1000,{'task':1000},protected or {},PROOF)
    value=OpeningImport(OpeningBalance('opening','fixture:source','reportedTokens:fixture:v1',
                        {'task':spent},0,() if pending is not None else None,PROOF,PROOF),
                        (p,),tuple(historical),tuple(pending) if pending is not None else None,
                        (SourceBaseline(p.profile_id,'epoch:1',0,100,PROOF),) if cumulative else (),
                        tuple(unknown),partials or {},PROOF if pending is not None else None,
                        CloseoutLineage('policy',1,protected or {},PROOF))
    return BudgetScope(scope,scope,'reportedTokens:fixture:v1'),policy,value


def history(op, amount):
    obs=observation([op],[amount],event='historical:'+op.budget_scope_id+':'+op.operation_id)
    return HistoricalCharge(op,obs.receipts[0],'fixture:usage:v1',obs.atoms,'claim:'+op.operation_id,PROOF)


def paid(j,op):
    assert j.reserve(op)=='RESERVED'
    assert j.claim(op.budget_scope_id,op.operation_id,op.binding_digest,'claim:'+op.operation_id)=='CLAIM_GRANTED'
    return op


def race_worker(path,barrier,out,action,args):
    try:
        with Journal(path,PROOF) as j:
            barrier.wait(timeout=10)
            result=j.import_opening(*args) if action=='import' else j.ingest_usage('run',args)
            out.put(result.status)
    except JournalUnavailable:out.put('UNAVAILABLE')


def killed_ingest(path,obs,stage):
    with Journal(path,PROOF,fault_hook=lambda point:os._exit(17) if point==stage else None) as j:
        j.ingest_usage('run',obs)
    os._exit(18)


def unavailable_envelope(op, *, outer='outer-A', final='final-E'):
    obs=observation([op],[30],event=outer,kind='SNAPSHOT')
    raw=canonical({'outer':outer,'total':None,'final':final,'actual':30})
    ref=EvidenceRef('fixture:missing-total:'+outer,hashlib.sha256(raw.encode()).hexdigest())
    return replace(obs,total=None,raw=raw,raw_evidence=ref,
                   receipts=(replace(obs.receipts[0],source_event_id=final,raw_evidence=ref),))


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'v2.db'
        self.j=Journal(self.path,PROOF)
    def tearDown(self):self.j.close();self.temp.cleanup()
    def opened(self,**kwargs):
        args=import_data(**kwargs);self.assertEqual(self.j.import_opening(*args).status,'IMPORTED');return args
    def keys(self):
        return [tuple(x) for x in self.j._db.execute("SELECT * FROM identities WHERE kind IN ('source','settlement') ORDER BY kind,key")]

    def test_private_financial_primitives_commit_and_rollback_with_outer_transaction(self):
        self.opened()
        rolled_back = operation(name='rolled-back', upper=10)
        with self.assertRaises(JournalUnavailable):
            _reserve_in_transaction(self.j, rolled_back)
        with self.assertRaises(RuntimeError):
            with self.j._transaction():
                self.assertEqual(_reserve_in_transaction(self.j, rolled_back), 'RESERVED')
                self.assertEqual(_claim_in_transaction(
                    self.j, 'run', rolled_back.operation_id, rolled_back.binding_digest, 'claim:rolled-back'
                ), 'CLAIM_GRANTED')
                self.assertEqual(self.j._load('run')[0]['operations'][rolled_back.operation_id]['claim_id'],
                                 'claim:rolled-back')
                raise RuntimeError('fixture rollback before commit')
        self.assertNotIn(rolled_back.operation_id, self.j._load('run')[0]['operations'])
        with self.j._transaction():
            self.assertEqual(_reserve_in_transaction(self.j, rolled_back), 'RESERVED')
            self.assertEqual(_claim_in_transaction(
                self.j, 'run', rolled_back.operation_id, rolled_back.binding_digest, 'claim:rolled-back'
            ), 'CLAIM_GRANTED')
        self.assertEqual(self.j.reserve(rolled_back), 'ALREADY_RESERVED')
        self.assertEqual(self.j.claim('run', rolled_back.operation_id, rolled_back.binding_digest,
                                      'claim:another'), 'ALREADY_CLAIMED')
        self.assertEqual(self.j.rebuild('run'), self.j.snapshot('run'))

    def test_storage_stream_empty_delta_and_rebuild_corruption_rollback(self):
        self.opened()
        before, _ = self.j._load('run')
        obs = observation([], [], kind='STREAM', event='stream-empty')
        self.assertEqual(self.j.ingest_usage('run', obs).status, 'OBSERVATION_RECORDED')
        event = self.j.events('run')[-1]
        payload = json.loads(event['payload'])
        self.assertNotIn('after', payload)
        self.assertEqual(payload['state_delta']['changes'], [])
        self.assertEqual(payload['state_delta']['base_digest'], digest(before))
        self.assertEqual(payload['state_delta']['result_digest'], digest(before))
        self.assertEqual(canonical(self.j._load('run')[0]), canonical(before))
        projection = self.j.snapshot('run')
        self.assertEqual(self.j.rebuild('run'), projection)
        # A rebuild restores indexes before decoding events. A later corrupt
        # delta must roll that restoration back along with the projection.
        trigger = self.j._db.execute(
            "SELECT sql FROM sqlite_master WHERE name='protect_source_observations_delete'").fetchone()[0]
        self.j._db.execute('DROP TRIGGER protect_source_observations_delete')
        self.j._db.execute('DELETE FROM source_observations')
        self.j._db.execute(trigger)
        trigger = self.j._db.execute(
            "SELECT sql FROM sqlite_master WHERE name='protect_events_update'").fetchone()[0]
        for corrupt in ('base', 'result', 'mixed', 'missing'):
            with self.subTest(corrupt=corrupt):
                changed = copy.deepcopy(payload)
                if corrupt in ('base', 'result'):
                    changed['state_delta'][corrupt + '_digest'] = '0' * 64
                elif corrupt == 'mixed': changed['after'] = before
                else: del changed['state_delta']
                self.j._db.execute('DROP TRIGGER protect_events_update')
                self.j._db.execute('UPDATE events SET payload=?,digest=? WHERE event_id=?',
                                   (canonical(changed), digest(changed), event['event_id']))
                self.j._db.execute(trigger)
                frozen = list(self.j._db.iterdump())
                with self.assertRaises(JournalUnavailable):
                    self.j.rebuild('run')
                self.assertEqual(list(self.j._db.iterdump()), frozen)
                self.assertEqual(self.j.snapshot('run'), projection)

    def test_impl_f01_monotonic_partial_and_runtime_composition(self):
        args=self.opened(spent=None,unknown=(PROOF,),partials={'task':7})
        zero=replace(args[2],known_partials={'task':0})
        first=self.j.reconcile_import('run',ImportAmendment(digest(asdict(args[2])),zero,PROOF))
        complete=replace(zero,opening=replace(zero.opening,task_spent={'task':0}),unknown_intervals=())
        self.j.reconcile_import('run',ImportAmendment(digest(asdict(args[2])),complete,PROOF))
        with self.subTest(case='partial7-to0-to-complete0'):
            self.assertEqual(first.status,'CONFLICT')
            self.assertGreaterEqual(self.j.snapshot('run').known_spent,7)
            self.assertNotEqual(self.j.snapshot('run').gate_status,'READY')
        op=operation('partial-runtime',upper=10)
        args=self.opened(scope='partial-runtime',spent=None,unknown=(PROOF,),partials={'task':7},
                         pending=(PendingImport(op,'original-claim',PROOF,'UNAVAILABLE'),))
        self.assertEqual(self.j.ingest_usage('partial-runtime',observation([op],[8],event='partial-runtime:final')).status,'SETTLED')
        self.assertEqual(self.j.snapshot('partial-runtime').known_spent,15)
        more=replace(args[2],known_partials={'task':9})
        result=self.j.reconcile_import('partial-runtime',ImportAmendment(digest(asdict(args[2])),more,PROOF))
        with self.subTest(case='historical9-plus-runtime8'):
            self.assertEqual(result.status,'RECONCILED')
            p=self.j.snapshot('partial-runtime');self.assertEqual(p.known_spent,17)
            self.assertIsNone(p.spent);self.assertEqual(self.j.rebuild('partial-runtime'),p)

    def test_impl_f02_global_uncertainty_cannot_be_cleared_indirectly(self):
        for pending in (False,True):
            scope='reason-pending' if pending else 'reason-settled';args=self.opened(scope=scope,cumulative=True)
            op=paid(self.j,operation(scope,name='A'))
            if not pending:
                self.j.ingest_usage(scope,observation([op],[30],event=scope+':130',kind='SNAPSHOT',total=130,sequence=1))
            reset=observation([op],[5],event=scope+':reset',kind='SNAPSHOT',total=5,sequence=2)
            self.assertEqual(self.j.ingest_usage(scope,reset).status,'UNAVAILABLE')
            if pending:
                self.j.cancel_without_dispatch(scope,'A',PROOF)
            amended=replace(args[2],inventory_proof=EvidenceRef('fixture:new-inventory','c'*64))
            self.j.reconcile_import(scope,ImportAmendment(digest(asdict(args[2])),amended,PROOF))
            with self.subTest(case=scope):
                self.assertNotEqual(self.j.snapshot(scope).gate_status,'READY')
                self.assertIsNone(self.j.snapshot(scope).spent)
        args=self.opened(scope='reason-overflow');op=paid(self.j,operation('reason-overflow'))
        self.j.ingest_usage('reason-overflow',observation([op],[MAX_INTEGER+1],event='reason-overflow:final'))
        amended=replace(args[2],inventory_proof=EvidenceRef('fixture:new-inventory','c'*64))
        self.j.reconcile_import('reason-overflow',ImportAmendment(digest(asdict(args[2])),amended,PROOF))
        with self.subTest(case='overflow-total-stays-null'):
            self.assertIsNone(self.j.snapshot('reason-overflow').spent)
            self.assertEqual(self.j.snapshot('reason-overflow').gate_status,'BOUND_BROKEN')

    def test_impl_f03_nested_final_identity_preflight_and_persistence(self):
        for reverse in (False,True):
            for legacy in (False,True):
                scope=f'nested:{reverse}:{legacy}';other=scope+':other';key=scope+':E'
                self.opened(scope=scope);self.opened(scope=other)
                a=paid(self.j,operation(scope));b=paid(self.j,operation(other))
                envelope=unavailable_envelope(a,outer=scope+':outer',final=key)
                leaf=observation([b],[30],event=key)
                if reverse:
                    self.j.ingest_usage(other,leaf)
                    result=self.j.ingest_usage(scope,envelope).status
                else:
                    self.j.ingest_usage(scope,envelope)
                    result=self.j.record_settlement(leaf.receipts[0]) if legacy else self.j.ingest_usage(other,leaf).status
                with self.subTest(reverse=reverse,legacy=legacy):
                    self.assertEqual(result,'CONFLICT')
                    self.assertEqual(self.j.snapshot(scope).gate_status,'CONFLICT')
                    self.assertEqual(self.j.snapshot(other).known_spent,30 if reverse else 0)
        self.opened(scope='early');op=paid(self.j,operation('early'))
        leaf=observation([op],[30],event='early:E');self.j.ingest_usage('early',leaf)
        unknown=operation('absent',name='unknown')
        envelope=unavailable_envelope(unknown,outer='absent:outer',final='early:E')
        with self.subTest(case='missing-scope-preflight'):
            self.assertEqual(self.j.ingest_usage('absent',envelope).status,'CONFLICT')
            self.assertEqual(self.j.snapshot('early').gate_status,'CONFLICT')

    def test_impl_nested_batch_conflicts_are_atomic_and_quarantine_all_owners(self):
        for scope in ('batch','old-A','old-B','internal'):
            self.opened(scope=scope)
        old=[]
        for scope in ('old-A','old-B'):
            op=paid(self.j,operation(scope))
            obs=observation([op],[10],event=scope+':E');self.j.ingest_usage(scope,obs);old.append(obs)
        ops=[paid(self.j,operation('batch',name=x)) for x in ('new','A','B')]
        obs=observation(ops,[10,10,10],event='batch:outer',kind='SNAPSHOT')
        receipts=tuple(replace(r,source_event_id=e) for r,e in zip(obs.receipts,('batch:new','old-A:E','old-B:E')))
        result=self.j.ingest_usage('batch',replace(obs,total=None,receipts=receipts))
        self.assertEqual(result.status,'CONFLICT')
        for scope in ('batch','old-A','old-B'):
            with self.subTest(scope=scope):self.assertEqual(self.j.snapshot(scope).gate_status,'CONFLICT')
        self.assertEqual(self.j.snapshot('batch').known_spent,0)
        self.assertFalse(self.j._db.execute("SELECT 1 FROM identities WHERE key=?",(canonical(['fixture:source','batch:new']),)).fetchone())
        self.assertFalse(self.j._db.execute("SELECT 1 FROM source_observations WHERE scope='batch'").fetchone())
        a,b=[paid(self.j,operation('internal',name=x)) for x in ('A','B')]
        stream=observation([a,b],[10,10],event='internal:stream',kind='STREAM')
        stream=replace(stream,receipts=tuple(replace(r,source_event_id='internal:same') for r in stream.receipts))
        self.assertEqual(self.j.ingest_usage('internal',stream).status,'CONFLICT')
        self.assertEqual(self.j.snapshot('internal').known_spent,0)
        self.assertFalse(self.j._db.execute("SELECT 1 FROM identities WHERE key=?",(canonical(['fixture:source','internal:same']),)).fetchone())

    def test_impl_frontier_history_completion_and_missing_order(self):
        a=operation(name='A');h=operation(name='H')
        args=self.opened(cumulative=True,spent=None,unknown=(PROOF,),
                         pending=(PendingImport(a,'claim:A',PROOF,'UNAVAILABLE'),))
        one=observation([a],[20],event='history:120',kind='SNAPSHOT',total=120)
        self.assertEqual(self.j.ingest_usage('run',one).status,'SETTLED')
        completed=replace(args[2],historical=(history(h,30),),unknown_intervals=(),
                          opening=replace(args[2].opening,task_spent={'task':30}))
        self.assertEqual(self.j.reconcile_import('run',ImportAmendment(digest(asdict(args[2])),completed,PROOF)).status,'RECONCILED')
        self.assertEqual(self.j.snapshot('run').spent,50)
        repeat=observation([h],[30],event='history:150',kind='SNAPSHOT',total=150,sequence=2)
        self.assertIn(self.j.ingest_usage('run',repeat).status,{'CONFLICT','UNAVAILABLE'})
        self.assertEqual(self.j.snapshot('run').known_spent,50)
        self.opened(scope='no-order',cumulative=True);op=paid(self.j,operation('no-order'))
        absent=replace(observation([op],[30],event='no-order:130',kind='SNAPSHOT',total=130),interval_memberships=())
        self.assertEqual(self.j.ingest_usage('no-order',absent).status,'UNAVAILABLE')
        self.assertEqual(self.j.snapshot('no-order').known_spent,0)

    def test_impl_f04_cumulative_atom_cannot_cover_two_increments(self):
        self.opened(cumulative=True);op=paid(self.j,operation(name='A'))
        first=observation([op],[30],event='frontier:130',kind='SNAPSHOT',total=130,sequence=1)
        self.assertEqual(self.j.ingest_usage('run',first).status,'SETTLED')
        before=copy.deepcopy(self.j._load('run')[0]['baselines'])
        repeated=observation([op],[30],event='frontier:160',kind='SNAPSHOT',total=160,sequence=2)
        result=self.j.ingest_usage('run',repeated)
        self.assertIn(result.status,{'CONFLICT','UNAVAILABLE'})
        self.assertEqual(self.j._load('run')[0]['baselines'],before)
        self.assertEqual(self.j.snapshot('run').known_spent,30)
        self.assertNotEqual(self.j.snapshot('run').gate_status,'READY')

    def test_impl_f05_unseen_consistent_intermediate_point(self):
        self.opened(cumulative=True)
        a,b=paid(self.j,operation(name='A')),paid(self.j,operation(name='B'))
        endpoint=observation([a,b],[30,30],event='late:160',kind='SNAPSHOT',total=160,sequence=2,
                             intervals=((0,1),(1,2)))
        self.assertEqual(self.j.ingest_usage('run',endpoint).status,'SETTLED')
        before=copy.deepcopy(self.j._load('run')[0]['baselines'])
        late=observation([a],[30],event='late:130',kind='SNAPSHOT',total=130,sequence=1)
        result=self.j.ingest_usage('run',late)
        self.assertIn(result.status,{'CORROBORATED','OBSERVATION_RECORDED'})
        p=self.j.snapshot('run');self.assertEqual((p.spent,p.gate_status),(60,'READY'))
        # Evidence may add a proved checkpoint, but never move the financial endpoint.
        current=self.j._load('run')[0]['baselines']
        self.assertEqual([(x['sequence'],x['total']) for x in current.values()],[(x['sequence'],x['total']) for x in before.values()])
        self.assertEqual(self.j.rebuild('run'),p)

    def test_impl_f05_derived_lower_checkpoint_and_reopen(self):
        self.opened(cumulative=True)
        a,b,c=[paid(self.j,operation(name=name)) for name in ('A','B','C')]
        endpoint=observation([a,b,c],[30,30,40],event='derived:200',kind='SNAPSHOT',
                             total=200,sequence=3,intervals=((0,1),(1,2),(2,3)))
        self.assertEqual(self.j.ingest_usage('run',endpoint).status,'SETTLED')
        initial=copy.deepcopy(self.j._load('run')[0]);key=canonical(['fixture:usage:v1','epoch:1'])
        self.assertEqual(initial['baselines'][key]['checkpoints'],{'0':100,'3':200})
        late=observation([b],[30],event='derived:160',kind='SNAPSHOT',total=160,
                         sequence=2,intervals=((1,2),))
        self.assertEqual(self.j.ingest_usage('run',late).status,'CORROBORATED')
        state=self.j._load('run')[0];baseline=state['baselines'][key]
        self.assertEqual((baseline['sequence'],baseline['total']),(3,200))
        self.assertEqual(baseline['checkpoints']['2'],160)
        self.assertEqual(state['accepted_finals'],initial['accepted_finals'])
        saved=self.j.snapshot('run');self.assertEqual((saved.spent,saved.gate_status),(100,'READY'))
        self.assertEqual(self.j.ingest_usage('run',late).status,'ALREADY_CORROBORATED')
        self.assertEqual(self.j.snapshot('run'),saved)
        self.j.close();self.j=Journal(self.path,PROOF)
        self.assertEqual(self.j.rebuild('run'),saved)
        self.assertEqual(self.j._load('run')[0]['accepted_finals'],initial['accepted_finals'])

    def test_impl_f05_derived_lower_still_requires_indivisible_boundary(self):
        self.opened(cumulative=True)
        a,b,c=[paid(self.j,operation(name=name)) for name in ('A','B','C')]
        endpoint=observation([a,b,c],[30,30,40],event='split:200',kind='SNAPSHOT',
                             total=200,sequence=3,intervals=((0,2),(1,2),(2,3)))
        self.assertEqual(self.j.ingest_usage('run',endpoint).status,'SETTLED')
        initial=copy.deepcopy(self.j._load('run')[0])
        late=observation([b],[30],event='split:160',kind='SNAPSHOT',total=160,
                         sequence=2,intervals=((1,2),))
        self.assertEqual(self.j.ingest_usage('run',late).status,'UNAVAILABLE')
        state=self.j._load('run')[0]
        self.assertEqual(state['baselines'],initial['baselines'])
        self.assertEqual(state['accepted_finals'],initial['accepted_finals'])
        saved=self.j.snapshot('run');self.assertEqual(saved.known_spent,100)
        self.assertIsNone(saved.spent);self.assertEqual(saved.gate_status,'INCOMPLETE')
        self.assertEqual(self.j.rebuild('run'),saved)

    def test_impl_frontier_leaf_first_and_unprovable_late_point(self):
        args=import_data(cumulative=True)
        leaf_profile=replace(args[2].profiles[0],profile_id='fixture:leaf',counter_mode='OPERATION_FINAL')
        value=replace(args[2],profiles=(*args[2].profiles,leaf_profile))
        self.assertEqual(self.j.import_opening(args[0],args[1],value).status,'IMPORTED')
        op=paid(self.j,operation(name='A'))
        leaf=replace(observation([op],[30],event='frontier:leaf'),profile_id=leaf_profile.profile_id)
        self.assertEqual(self.j.ingest_usage('run',leaf).status,'SETTLED')
        first=observation([op],[30],event='frontier:initial',kind='SNAPSHOT',total=130,sequence=1)
        self.assertEqual(self.j.ingest_usage('run',first).status,'CORROBORATED')
        self.assertEqual(self.j.snapshot('run').spent,30)
        self.assertEqual(self.j.rebuild('run').spent,30)
        self.opened(scope='indivisible',cumulative=True)
        op=paid(self.j,operation('indivisible',name='A'))
        endpoint=observation([op],[60],event='indivisible:160',kind='SNAPSHOT',total=160,sequence=2,intervals=((0,2),))
        self.assertEqual(self.j.ingest_usage('indivisible',endpoint).status,'SETTLED')
        prior=copy.deepcopy(self.j._load('indivisible')[0]['baselines'])
        late=observation([op],[60],event='indivisible:130',kind='SNAPSHOT',total=130,sequence=1)
        self.assertEqual(self.j.ingest_usage('indivisible',late).status,'UNAVAILABLE')
        self.assertEqual(self.j._load('indivisible')[0]['baselines'],prior)
        self.assertEqual(self.j.snapshot('indivisible').known_spent,60)

    def test_v03_parent_leaf_both_orders_and_immutable_first_final(self):
        for parent_first in (True,False):
            scope='parentfirst' if parent_first else 'leaffirst';self.opened(scope=scope)
            a,b=paid(self.j,operation(scope,name='A')),paid(self.j,operation(scope,name='B'))
            parent=observation([a,b],[60,40],event=scope+':parent',kind='PARENT')
            leaves=[observation([op],[amount],event=scope+':leaf:'+op.operation_id) for op,amount in ((a,60),(b,40))]
            first=[parent] if parent_first else leaves;last=leaves if parent_first else [parent]
            for obs in first:self.assertEqual(self.j.ingest_usage(scope,obs).status,'SETTLED')
            original=self.keys();accepted=copy.deepcopy(self.j._load(scope)[0]['accepted_finals'])
            for obs in last:
                self.assertEqual(self.j.ingest_usage(scope,obs).status,'CORROBORATED')
                self.assertEqual(self.j.ingest_usage(scope,obs).status,'ALREADY_CORROBORATED')
            self.assertTrue(all(row in self.keys() for row in original))
            self.assertEqual(self.j._load(scope)[0]['accepted_finals'],accepted)
            before=self.j.snapshot(scope);self.assertEqual(before.spent,100);self.assertEqual(before.gate_status,'READY')
            self.assertEqual(self.j.rebuild(scope),before)

    def test_v04_opening_inclusion_and_null_inventory(self):
        a,b,c=operation(name='A'),operation(name='B'),operation(name='C',task=None)
        historical=tuple(history(o,n) for o,n in ((a,70),(b,20),(c,10)))
        scope,policy,value=import_data(historical=historical,spent=90)
        value=replace(value,opening=replace(value.opening,run_overhead=10))
        self.assertEqual(self.j.import_opening(scope,policy,value).status,'IMPORTED')
        self.assertEqual(self.j.import_opening(scope,policy,value).status,'ALREADY_IMPORTED')
        self.assertEqual(self.j.snapshot('run').spent,100)
        self.assertEqual(self.j.record_settlement(historical[0].receipt),'ALREADY_SETTLED')
        self.assertEqual(self.j.snapshot('run').spent,100)
        self.opened(scope='unknown',spent=None,pending=None,partials={'task':7})
        unknown=self.j.snapshot('unknown');self.assertEqual(unknown.known_spent,7)
        self.assertIsNone(unknown.spent);self.assertIsNone(unknown.active_reservations)
        self.assertEqual(self.j.reserve(operation('unknown')),'UNAVAILABLE')

    def test_v05_historical_and_pending_closeout(self):
        for cancel in (False,True):
            scope='cancel' if cancel else 'settle'
            a=operation(scope,name='A',upper=25,closeout=True)
            b=operation(scope,name='B',upper=10,closeout=True)
            args=self.opened(scope=scope,historical=(history(a,20),),spent=20,protected={'task':40},
                             pending=(PendingImport(b,'old-claim',PROOF,'UNAVAILABLE'),))
            before=self.j.snapshot(scope)
            self.assertEqual((before.protected_closeout,before.active_reservations,before.known_spent),(10,10,20))
            self.assertEqual(self.j.claim(scope,'B',b.binding_digest,'again'),'ALREADY_CLAIMED')
            if cancel:
                self.assertEqual(self.j.cancel_without_dispatch(scope,'B',PROOF),'CANCELLED')
                expected=(20,0,20)
            else:
                obs=observation([b],[8],event=scope+':B-final')
                self.assertEqual(self.j.ingest_usage(scope,obs).status,'SETTLED')
                self.assertEqual(self.j.ingest_usage(scope,obs).status,'ALREADY_SETTLED')
                expected=(12,0,28)
                self.assertEqual(self.j.reserve(operation(scope,name='C',upper=13,closeout=True)),'DENY')
            final=self.j.snapshot(scope)
            self.assertEqual((final.protected_closeout,final.active_reservations,final.spent),expected)
            self.assertEqual(self.j.import_opening(*args).status,'ALREADY_IMPORTED')
            self.assertEqual(self.j.rebuild(scope),final)
        op=operation('over',upper=10,closeout=True)
        self.opened(scope='over',historical=(history(op,12),),spent=12,protected={'task':40})
        p=self.j.snapshot('over');self.assertEqual((p.known_spent,p.protected_closeout,p.gate_status),(12,30,'BOUND_BROKEN'))
        scope,policy,value=import_data(scope='lineage',protected={'task':40})
        self.assertEqual(self.j.import_opening(scope,policy,replace(value,closeout_lineage=None)).status,'IMPORTED')
        self.assertIsNone(self.j.snapshot('lineage').protected_closeout)
        self.assertEqual(self.j.reserve(operation('lineage',closeout=True)),'UNAVAILABLE')

    def test_v02_cumulative_reorder_and_reset_journal(self):
        self.opened(cumulative=True)
        a,b=paid(self.j,operation(name='A')),paid(self.j,operation(name='B'))
        one=observation([a],[30],event='130',kind='SNAPSHOT',total=130,sequence=1)
        two=observation([b],[30],event='160',kind='SNAPSHOT',total=160,sequence=2)
        for obs in (one,two):self.assertEqual(self.j.ingest_usage('run',obs).status,'SETTLED')
        self.assertEqual(self.j.ingest_usage('run',one).status,'ALREADY_SETTLED')
        self.assertEqual(self.j.snapshot('run').spent,60)
        baseline=copy.deepcopy(self.j._load('run')[0]['baselines'])
        bad=observation([b],[5],event='reset',kind='SNAPSHOT',total=5,sequence=3)
        self.assertEqual(self.j.ingest_usage('run',bad).status,'UNAVAILABLE')
        self.assertEqual(self.j._load('run')[0]['baselines'],baseline)
        self.assertEqual(self.j.snapshot('run').known_spent,60)

    def test_v06_fault_rollback_aliases_and_process_death(self):
        for stage in ('after_keys','after_atoms','after_aliases','after_event','after_projection','after_baseline','before_commit'):
            scope='fault:'+stage;self.opened(scope=scope)
            op=paid(self.j,operation(scope));parent=observation([op],[60],event=scope+':parent',kind='PARENT')
            self.j.ingest_usage(scope,parent)
            leaf=observation([op],[60],event=scope+':leaf')
            before=self.j.snapshot(scope);keys=self.keys();events=self.j.events(scope)
            self.j.fault_hook=lambda point:(_ for _ in ()).throw(RuntimeError('injected')) if point==stage else None
            with self.assertRaises(RuntimeError):self.j.ingest_usage(scope,leaf)
            self.j.fault_hook=None
            self.assertEqual(self.j.snapshot(scope),before);self.assertEqual(self.keys(),keys);self.assertEqual(self.j.events(scope),events)
            self.assertEqual(self.j.rebuild(scope),before)
            self.assertEqual(self.j.ingest_usage(scope,leaf).status,'CORROBORATED')
        self.opened();op=paid(self.j,operation());obs=observation([op],[60])
        ctx=multiprocessing.get_context('spawn');p=ctx.Process(target=killed_ingest,args=(str(self.path),obs,'before_commit'))
        p.start();p.join(15)
        if p.is_alive():p.terminate();p.join();self.fail('Process did not exit')
        self.assertEqual(p.exitcode,17)
        recovered=self.j.rebuild('run');self.assertEqual(recovered.known_spent,0);self.assertEqual(recovered.active_reservations,100)
        self.assertEqual(self.j.ingest_usage('run',obs).status,'SETTLED')

    def test_v06_two_process_import_and_ingest(self):
        ctx=multiprocessing.get_context('spawn')
        for action in ('import','ingest'):
            path=Path(self.temp.name)/(action+'.db');args=import_data()
            with Journal(path,PROOF) as j:
                if action=='ingest':j.import_opening(*args);paid(j,operation());args=observation([operation()],[60])
            barrier,out=ctx.Barrier(2),ctx.Queue()
            workers=[ctx.Process(target=race_worker,args=(str(path),barrier,out,action,args)) for _ in range(2)]
            for child in workers:child.start()
            results=[out.get(timeout=15) for _ in workers]
            for child in workers:
                child.join(15)
                if child.is_alive():child.terminate();child.join();self.fail('Writer did not terminate')
                self.assertEqual(child.exitcode,0)
            out.close()
            self.assertCountEqual(results,['IMPORTED','ALREADY_IMPORTED'] if action=='import' else ['SETTLED','ALREADY_SETTLED'])
            with Journal(path,PROOF) as j:self.assertEqual(j.snapshot('run').spent,0 if action=='import' else 60)

    def test_v07_explicit_migration_failure_and_preservation(self):
        for fail_at in (None,'before_version','after_version'):
            path=Path(self.temp.name)/('migration-'+str(fail_at)+'.db')
            with closing(sqlite3.connect(path)) as db, db:
                for stmt in BASE_STATEMENTS:db.execute(stmt)
                db.execute('INSERT INTO schema_metadata VALUES(1,1)')
                for table in ('events','identities'):
                    for action in ('UPDATE','DELETE'):
                        db.execute(f'CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} '+"BEGIN SELECT RAISE(ABORT,'immutable journal record'); END")
            # Populate a valid v1 event/identity history, then compare raw SQL
            # rows across migration. This includes real historical final keys.
            from agent_lifecycle.accounting.journal import _apply
            oldop=operation('past');oldreceipt=receipt(oldop)
            sc,pol,imp=import_data(scope='past')
            payloads=[('OPEN',{'scope':asdict(sc),'policy':asdict(pol),'opening':asdict(imp.opening)}),
                      ('RESERVE',{'operation':asdict(oldop)}),
                      ('CLAIM',{'operation_id':'op','claim_id':'old-claim'}),
                      ('SETTLE',{'operation_id':'op','receipt':asdict(oldreceipt)})]
            oldstate=None
            with closing(sqlite3.connect(path)) as db, db:
                for revision,(kind,payload) in enumerate(payloads,1):
                    payload=json.loads(canonical(payload));oldstate=_apply(oldstate,kind,payload)
                    db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('old:'+str(revision),'past',revision,0,'tx:'+str(revision),kind,canonical(payload),digest(payload),canonical(asdict(PROOF)),'fixture:past'))
                db.execute('INSERT INTO scope_state VALUES(?,?,?)',('past',4,canonical(oldstate)))
                keys=[('operation',['past','op'],oldop.binding_digest),('dispatch',['past',oldop.dispatch_key],oldop.binding_digest),
                      ('permit',oldop.permit_id,oldop.binding_digest),('claim',oldop.permit_id,digest('old-claim')),
                      ('source',[oldreceipt.source_id,oldreceipt.source_event_id],digest(asdict(oldreceipt))),
                      ('settlement',['past','op'],digest(asdict(oldreceipt)))]
                for kind,key,checksum in keys:db.execute('INSERT INTO identities VALUES(?,?,?,?,?)',(kind,canonical(key),'past','op',checksum))
                before_events=db.execute('SELECT * FROM events ORDER BY revision').fetchall()
                before_keys=db.execute('SELECT * FROM identities ORDER BY kind,key').fetchall()
            with self.assertRaises(JournalUnavailable):Journal(path,PROOF)
            def fault(point):
                if point==fail_at:raise RuntimeError('migration failure')
            if fail_at:
                with self.assertRaises(RuntimeError):Journal.migrate_v1(path,PROOF,fault_hook=fault)
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertEqual(db.execute('SELECT version FROM schema_metadata').fetchone()[0],1)
                    self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='coverage_atoms'").fetchone())
            Journal.migrate_v1(path,PROOF)
            with Journal(path,PROOF) as j:
                self.assertEqual([tuple(r) for r in j._db.execute('SELECT * FROM events ORDER BY revision')],before_events)
                self.assertEqual([tuple(r) for r in j._db.execute('SELECT * FROM identities ORDER BY kind,key')],before_keys)
                self.assertEqual(j.rebuild('past').spent,80)
                from .test_journal import open_scope
                open_scope(j);paid(j,operation());self.assertEqual(j.record_settlement(receipt(operation())),'SETTLED')
                self.assertEqual(j.rebuild('run').spent,80)

    def test_v08_unknown_completion_sticky_and_overlap(self):
        args=self.opened(spent=None,unknown=(PROOF,),partials={'task':7})
        op=operation();charge=history(op,10)
        complete=replace(args[2],opening=replace(args[2].opening,task_spent={'task':10}),
                         historical=(charge,),unknown_intervals=(),known_partials={})
        amendment=ImportAmendment(digest(asdict(args[2])),complete,PROOF)
        self.assertEqual(self.j.reconcile_import('run',amendment).status,'RECONCILED')
        self.assertEqual(self.j.snapshot('run').spent,10)
        self.assertEqual(self.j.reconcile_import('run',amendment).status,'ALREADY_RECONCILED')
        self.assertEqual(self.j.rebuild('run').spent,10)
        bad=replace(complete,opening=replace(complete.opening,task_spent={'task':9}))
        self.assertEqual(self.j.reconcile_import('run',replace(amendment,completed_import=bad)).status,'UNAVAILABLE')
        # Explicitly conflicting already-used source leaves CONFLICT sticky.
        self.assertEqual(self.j.record_settlement(replace(charge.receipt,reported_tokens=11)),'CONFLICT')
        self.assertEqual(self.j.rebuild('run').gate_status,'CONFLICT')

    def test_v10_individual_semantic_and_legacy_bypass_guards(self):
        for change in ('amount','atoms','binding','raw'):
            scope='mismatch:'+change;self.opened(scope=scope)
            op=paid(self.j,operation(scope));first=observation([op],[60],event=scope+':first')
            self.assertEqual(self.j.ingest_usage(scope,first).status,'SETTLED')
            if change=='amount':other=observation([op],[61],event=scope+':second')
            elif change=='atoms':other=observation([op],[60],event=scope+':second',atoms=(atom(op,60,name='different'),))
            elif change=='binding':
                altered=replace(op,attempt_id='changed-attempt')
                other=observation([altered],[60],event=scope+':second')
            else:other=observation([op],[61],event=scope+':first')
            self.assertEqual(self.j.ingest_usage(scope,other).status,'CONFLICT')
            self.assertEqual(self.j.snapshot(scope).known_spent,60)
        self.opened(scope='old-entry');op=paid(self.j,operation('old-entry'))
        self.assertEqual(self.j.record_settlement(receipt(op)),'UNAVAILABLE')
        self.assertEqual(self.j.snapshot('old-entry').active_reservations,100)
        self.opened(scope='profile-change')
        p=replace(profile('profile-change'),profile_id='new-identity',coverage_namespace='fixture:other')
        self.assertEqual(self.j.register_source_profile('profile-change',p).status,'UNAVAILABLE')
        self.assertNotIn('new-identity',self.j._load('profile-change')[0]['profiles'])
        self.opened(scope='ghost');op=paid(self.j,operation('ghost'))
        self.j.ingest_usage('ghost',observation([op],[60],event='ghost:parent',kind='PARENT'))
        leaf=observation([op],[60],event='ghost:leaf');self.j.ingest_usage('ghost',leaf)
        self.assertEqual(self.j.record_settlement(replace(leaf.receipts[0],operation_id='unknown')),'CONFLICT')

    def test_v08_qualified_final_resolves_operation_only_uncertainty(self):
        self.opened();op=paid(self.j,operation());obs=observation([op],[60])
        self.assertEqual(self.j.record_settlement(obs.receipts[0]),'UNAVAILABLE')
        self.assertEqual(self.j.snapshot('run').gate_status,'INCOMPLETE')
        self.assertEqual(self.j.ingest_usage('run',obs).status,'SETTLED')
        p=self.j.snapshot('run')
        self.assertEqual((p.spent,p.active_reservations,p.gate_status),(60,0,'READY'))
        self.assertEqual(self.j.rebuild('run'),p)
        # Unsettled legacy evidence has an immutable global identity too.
        self.opened(scope='pending-identity');other=paid(self.j,operation('pending-identity'))
        earlier=observation([other],[60],event='pending-identity:event')
        self.assertEqual(self.j.record_settlement(earlier.receipts[0]),'UNAVAILABLE')
        altered=observation([other],[59],event='pending-identity:event')
        self.assertEqual(self.j.ingest_usage('pending-identity',altered).status,'CONFLICT')
        self.assertEqual(self.j.snapshot('pending-identity').active_reservations,100)

    def test_v06_two_process_corroboration_race(self):
        self.opened();op=paid(self.j,operation())
        self.j.ingest_usage('run',observation([op],[60],event='parent:race',kind='PARENT'))
        original=self.keys();obs=observation([op],[60],event='leaf:race')
        ctx=multiprocessing.get_context('spawn');barrier,out=ctx.Barrier(2),ctx.Queue()
        workers=[ctx.Process(target=race_worker,args=(str(self.path),barrier,out,'ingest',obs)) for _ in range(2)]
        for child in workers:child.start()
        results=[out.get(timeout=15) for _ in workers]
        for child in workers:
            child.join(15)
            if child.is_alive():child.terminate();child.join();self.fail('Alias writer did not terminate')
            self.assertEqual(child.exitcode,0)
        out.close();self.assertCountEqual(results,['CORROBORATED','ALREADY_CORROBORATED'])
        self.assertTrue(all(row in self.keys() for row in original))
        self.assertEqual(self.j.snapshot('run').spent,60)

    def test_v09_oversized_final_keeps_reservation_baseline_and_raw(self):
        self.opened();op=paid(self.j,operation())
        obs=observation([op],[MAX_INTEGER+1])
        self.assertEqual(self.j.ingest_usage('run',obs).status,'UNAVAILABLE')
        p=self.j.snapshot('run');self.assertEqual(p.active_reservations,100);self.assertIsNone(p.spent)
        self.assertEqual(p.gate_status,'BOUND_BROKEN');self.assertEqual(p.known_spent,0)
        self.assertIn(str(MAX_INTEGER+1),canonical(self.j.events('run')))
        self.assertEqual(self.j.rebuild('run'),p)

    def test_v10_alias_reuse_legacy_v2_and_mismatches(self):
        for legacy in (False,True):
            scope='legacy' if legacy else 'modern';other=scope+':other'
            self.opened(scope=scope);self.opened(scope=other)
            a=paid(self.j,operation(scope));b=paid(self.j,operation(other,name='other'))
            self.j.ingest_usage(scope,observation([a],[60],event=scope+':parent',kind='PARENT'))
            leaf=observation([a],[60],event=scope+':alias')
            self.assertEqual(self.j.ingest_usage(scope,leaf).status,'CORROBORATED')
            collision=observation([b],[60],event=scope+':alias')
            result=self.j.record_settlement(collision.receipts[0]) if legacy else self.j.ingest_usage(other,collision).status
            self.assertEqual(result,'CONFLICT');self.assertEqual(self.j.snapshot(scope).known_spent,60)
            self.assertEqual(self.j.snapshot(other).known_spent,0)
        self.opened();op=paid(self.j,operation());leaf=observation([op],[60])
        self.assertEqual(self.j.ingest_usage('run',leaf).status,'SETTLED')
        altered=observation([op],[61],event='different')
        self.assertEqual(self.j.ingest_usage('run',altered).status,'CONFLICT')
        self.assertEqual(self.j.snapshot('run').known_spent,60)
        with self.assertRaises(sqlite3.IntegrityError):self.j._db.execute('DELETE FROM corroborating_finals')
        state,rev=self.j._load('run')
        self.j._db.execute('INSERT INTO coverage_atoms VALUES(?,?,?,?,?)',('tampered','run','op','a'*64,'{}'))
        with self.assertRaises(JournalUnavailable):self.j.rebuild('run')



class RetentionTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'retention.db'
        self.j = Journal(self.path, PROOF)
        self.clock = lambda: datetime.now(timezone.utc)

    def tearDown(self):
        self.j.close(); self.temp.cleanup()

    def opened(self, scope='run', name='A', amount=10, **kwargs):
        self.assertEqual(self.j.import_opening(*import_data(scope, **kwargs)).status, 'IMPORTED')
        op = paid(self.j, operation(scope, name))
        obs = observation([op], [amount], event='original:' + name)
        self.assertEqual(self.j.ingest_usage(scope, obs).status, 'SETTLED')
        return op, obs

    def close_run(self, scope='run'):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import RunClosure
        now = self.clock() + timedelta(seconds=1)
        revision = self.j.snapshot(scope).journal_revision
        closure = RunClosure('closure:' + scope, scope, 'reportedTokens:fixture:v1', now.isoformat(),
                             ((scope, revision),), PROOF, PROOF)
        outcome = self.j.close_run(closure, now.isoformat())
        self.assertEqual(outcome.status, 'CLOSED')
        return closure, outcome

    def collected(self, scope='run'):
        c, outcome = self.close_run(scope)
        self.assertEqual(self.j.collect_closed_run(scope, outcome.eligible_after).status, 'COLLECTED')
        return c, outcome

    def count(self, table):
        return self.j._db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def lose_projection(self, table):
        """Explicit test-only fault; normal immutable DELETE remains forbidden."""
        name = 'protect_' + table + '_delete'
        trigger = self.j._db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
        self.j._db.execute('DROP TRIGGER ' + name)
        self.j._db.execute(f'DELETE FROM {table}')
        self.j._db.execute(trigger)

    def test_ret_f01_missing_global_identities_block_reuse_before_owner_rebuild(self):
        a, _ = self.opened('closed', 'A'); self.collected('closed')
        self.lose_projection('identities')
        self.assertEqual(self.j.import_opening(*import_data('active')).status, 'IMPORTED')
        b = replace(operation('active', 'B'), permit_id=a.permit_id)
        before = list(self.j._db.iterdump())
        with self.assertRaises(JournalUnavailable): self.j.reserve(b)
        self.assertEqual(list(self.j._db.iterdump()), before)
        archive = self.j._retained('archive_records', 'closed')
        for kind, key, scope, owner, checksum in archive['protection']['identities']:
            with self.subTest(kind=kind), self.assertRaises(JournalUnavailable), self.j._transaction():
                self.j._key(kind, key, 'active', 'B', digest(asdict(b)))
        self.assertEqual(list(self.j._db.iterdump()), before)
        self.assertEqual(self.j.rebuild('closed').known_spent, 10)
        for kind, key, scope, owner, checksum in archive['protection']['identities']:
            row = self.j._db.execute('SELECT * FROM identities WHERE kind=? AND key=?', (kind, canonical(key))).fetchone()
            self.assertEqual(tuple(row), (kind, canonical(key), scope, owner, checksum))
        self.assertEqual(self.j.reserve(b), 'CONFLICT')
        self.assertEqual(self.j.snapshot('active').active_reservations, 0)

    def test_ret_f01_missing_archived_financial_indexes_block_reuse(self):
        a, _ = self.opened('closed', 'A')
        self.assertEqual(self.j.ingest_usage('closed', observation([a], [10], event='alias:A')).status, 'CORROBORATED')
        self.collected('closed')
        archive = self.j._retained('archive_records', 'closed')
        self.assertEqual({entry['table'] for entry in archive['protection']['indexes']},
                         {'coverage_atoms', 'corroborating_finals'})
        for table in ('coverage_atoms', 'corroborating_finals'): self.lose_projection(table)
        self.assertEqual(self.j.import_opening(*import_data('active')).status, 'IMPORTED')
        before = list(self.j._db.iterdump())
        for entry in archive['protection']['indexes']:
            with self.subTest(table=entry['table']), self.assertRaises(JournalUnavailable), self.j._transaction():
                self.j._index(**{**entry, 'scope': 'active', 'owner': 'B'})
        self.assertEqual(list(self.j._db.iterdump()), before)
        self.assertEqual(self.j.rebuild('closed').known_spent, 10)
        for entry in archive['protection']['indexes']:
            row = self.j._db.execute(f"SELECT scope,owner FROM {entry['table']} WHERE key=?", (entry['key'],)).fetchone()
            self.assertEqual(tuple(row), ('closed', 'A'))

    def test_ret_f02_imported_and_completed_cancellations_keep_original_proof(self):
        for mode in ('import', 'completion', 'retained-through-completion'):
            for claim in (None, 'original-claim'):
                scope = mode + (':claimed' if claim else ':unclaimed')
                with self.subTest(mode=mode, claim=claim):
                    op = operation(scope, 'cancelled:' + scope)
                    proof = EvidenceRef('fixture:no-dispatch:' + scope, 'b' * 64)
                    item = PendingImport(op, claim, proof, 'CANCELLED_WITH_NO_DISPATCH_PROOF')
                    args = import_data(scope, pending=None if mode == 'completion' else (item,),
                                       spent=None if mode == 'retained-through-completion' else 0)
                    self.assertEqual(self.j.import_opening(*args).status, 'IMPORTED')
                    if mode != 'import':
                        completed = import_data(scope, pending=(item,))[2]
                        amendment = ImportAmendment(digest(asdict(args[2])), completed, PROOF)
                        self.assertEqual(self.j.reconcile_import(scope, amendment).status, 'RECONCILED')
                    runtime = paid(self.j, operation(scope, 'runtime:' + scope))
                    self.assertEqual(self.j.cancel_without_dispatch(scope, runtime.operation_id, PROOF), 'CANCELLED')
                    kind = 'IMPORT_EVIDENCE_COMPLETED' if mode == 'completion' else 'IMPORT_OPENING'
                    event = next(e for e in self.j.events(scope) if e['kind'] == kind)
                    evidence = json.loads(event['payload'])['evidence']
                    value = evidence['completed_import'] if mode == 'completion' else evidence
                    self.collected(scope)
                    archive = self.j._retained('archive_records', scope)
                    witnesses = {v['operation_id']: v for v in archive['protection']['cancellations']}
                    self.assertEqual(set(witnesses), {op.operation_id, runtime.operation_id})
                    witness = witnesses[op.operation_id]
                    self.assertEqual(witness['proof'], asdict(proof))
                    self.assertEqual(witness['event_kind'], kind)
                    self.assertEqual(witness['event_digest'], event['digest'])
                    self.assertEqual(witness['event_revision'], event['revision'])
                    self.assertEqual(witness['declaration_digest'], digest(asdict(item)))
                    self.assertEqual(witness['opening_digest'], digest(asdict(args[2])))
                    self.assertEqual(witness['import_digest'], digest(value))
                    self.assertEqual(witness['evidence_digest'], digest(evidence))
                    self.assertNotIn('opening_import', archive['state'])
                    self.j.close(); self.j = Journal(self.path, PROOF)
                    self.assertEqual(self.j.rebuild(scope).spent, 0)
                    self.assertEqual(self.j.permit(scope, op.operation_id).status, 'REVOKED')
                    self.assertEqual(self.j.events(scope), [])

    def test_ret_f03_fresh_batch_qualifies_all_closed_owners_atomically(self):
        for collected_first, collected_second in ((False, False), (True, False), (False, True), (True, True)):
            for origin_index in (0, 1):
                with self.subTest(collected=(collected_first, collected_second), origin=origin_index):
                    prefix = f'batch:{collected_first}:{collected_second}:{origin_index}:'
                    scopes = [prefix + 'first', prefix + 'second']
                    ops, outcomes = [], []
                    for index, collected in enumerate((collected_first, collected_second)):
                        scope = scopes[index]
                        op, _ = self.opened(scope, scope + ':op', 10 if index == 0 else 7)
                        ops.append(op)
                        outcomes.append((self.collected(scope) if collected else self.close_run(scope))[1])
                    late = observation(ops, [12, 9], event=prefix + 'late')
                    # After one closed-owner update, any failure must roll back both owners and all keys.
                    before = list(self.j._db.iterdump())
                    def fail(stage):
                        if stage == 'after_exception_quarantine': raise RuntimeError('after first closed owner')
                    self.j.fault_hook = fail
                    with self.assertRaises(RuntimeError): self.j.ingest_usage(scopes[origin_index], late)
                    self.j.fault_hook = None
                    self.assertEqual(list(self.j._db.iterdump()), before)
                    self.assertEqual(self.j.ingest_usage(scopes[origin_index], late).status, 'ACCOUNTING_RECONCILIATION_REQUIRED')
                    bindings = list(self.j._db.execute('SELECT payload FROM exception_identity_keys ORDER BY key'))
                    count = self.count('financial_exceptions')
                    for scope in scopes:
                        self.assertEqual(self.j._db.execute('SELECT COUNT(*) FROM financial_exceptions WHERE scope=?', (scope,)).fetchone()[0], 1)
                    self.assertEqual(self.j.ingest_usage(scopes[origin_index], late).status, 'ACCOUNTING_RECONCILIATION_REQUIRED')
                    self.assertEqual(self.count('financial_exceptions'), count)
                    self.assertEqual(list(self.j._db.execute('SELECT payload FROM exception_identity_keys ORDER BY key')), bindings)
                    self.j.close(); self.j = Journal(self.path, PROOF)
                    for index, scope in enumerate(scopes):
                        snap = self.j.rebuild(scope)
                        self.assertEqual(snap.known_spent, 10 if index == 0 else 7)
                        self.assertIsNone(snap.spent)
                        self.assertEqual(self.j.permit(scope, ops[index].operation_id).status, 'REVOKED')
                        expected = 'ALREADY_COLLECTED' if (collected_first, collected_second)[index] else 'ACCOUNTING_RECONCILIATION_REQUIRED'
                        self.assertEqual(self.j.collect_closed_run(scope, outcomes[index].eligible_after).status, expected)

    def test_ret_c01_complete_totals_inventory_overrun_and_refusals(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import RunClosure
        self.opened()
        c, result = self.close_run()
        self.assertEqual(self.j.close_run(c, c.closed_at_utc).status, 'ALREADY_CLOSED')
        summary = self.j.closed_run('run')['summary']
        self.assertEqual(summary['known_spent'], 10)
        self.assertEqual(summary['roles']['worker'], 10)
        for change in ({'closure_id':'changed'}, {'scope_revisions':(('run',0),)}, {'unit_definition_id':'other'}):
            with self.subTest(change=change), self.assertRaises(JournalUnavailable):
                self.j.close_run(replace(c, **change), c.closed_at_utc)
        self.assertEqual(self.j.import_opening(*import_data('pending')).status, 'IMPORTED')
        paid(self.j, operation('pending','P'))
        now = (self.clock()+timedelta(seconds=1)).isoformat()
        pending = RunClosure('pending-close','pending',c.unit_definition_id,now,
                             (('pending',self.j.snapshot('pending').journal_revision),),PROOF,PROOF)
        with self.assertRaises(JournalUnavailable): self.j.close_run(pending,now)
        self.assertEqual(self.j.import_opening(*import_data('overrun')).status,'IMPORTED')
        op=paid(self.j,operation('overrun','O',upper=9))
        self.assertEqual(self.j.ingest_usage('overrun',observation([op],[12],event='overrun')).status,'SETTLED_BOUND_BROKEN')
        self.close_run('overrun')
        facts=self.j.closed_run('overrun')['summary']['scopes']['overrun']['totals']
        self.assertEqual(facts['known_spent'],12);self.assertEqual(facts['bound_violations'],['O'])

    def test_ret_c02_closed_mutators_and_new_scope_never_grant(self):
        from agent_lifecycle.accounting.contracts import BudgetScope
        op, obs=self.opened(); self.collected()
        self.assertEqual(self.j.reserve(operation(name='fresh')),'CLOSED')
        self.assertEqual(self.j.claim('run','A',op.binding_digest,'new-claim'),'CLOSED')
        self.assertEqual(self.j.note_dispatch('run','A',PROOF),'CLOSED')
        self.assertEqual(self.j.note_unavailable('run','A',PROOF),'CLOSED')
        self.assertEqual(self.j.cancel_without_dispatch('run','A',PROOF),'CLOSED')
        self.assertEqual(self.j.register_source_profile('run',profile()).status,'CLOSED')
        scope,policy,opening=import_data('new-scope')
        self.assertEqual(self.j.import_opening(BudgetScope('new-scope','run',scope.unit_definition_id),policy,opening).status,'CLOSED')
        self.assertEqual(self.j.open_scope(BudgetScope('new-scope','run',scope.unit_definition_id),policy,opening.opening),'CLOSED')
        self.assertEqual(self.j.permit('run','A').status,'REVOKED')
        self.assertEqual(self.j.ingest_usage('run',obs).status,'ALREADY_SETTLED')
        self.assertEqual(self.j.record_settlement(obs.receipts[0]),'ALREADY_SETTLED')
        self.assertEqual(self.j.snapshot('run').known_spent,10)
        self.assertIsNone(self.j._db.execute("SELECT scope FROM scope_state WHERE scope='new-scope'").fetchone())

    def test_ret_c03_c04_boundary_disposition_and_active_run(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import utc_instant
        self.opened(); self.assertEqual(self.j.import_opening(*import_data('active')).status,'IMPORTED')
        active_before=self.j.events('active');c,outcome=self.close_run()
        before=self.j.events('run'); deadline=utc_instant(outcome.eligible_after)
        self.assertEqual(self.j.collect_closed_run('run',(deadline-timedelta(microseconds=1)).isoformat()).status,'NOT_DUE')
        self.assertEqual(self.j.events('run'),before)
        with self.assertRaises(ValueError):self.j.collect_closed_run('run','2026-10-30T00:00:00')
        self.assertEqual(self.j.collect_closed_run('run',outcome.eligible_after).status,'COLLECTED')
        for table in ('events','scope_state','input_evidence','source_observations','source_profiles','source_baselines'):
            self.assertEqual(self.j._db.execute(f'SELECT COUNT(*) FROM {table} WHERE scope=?',('run',)).fetchone()[0],0)
        self.assertEqual(self.j.events('active'),active_before)
        self.assertGreater(self.count('identities'),0);self.assertGreater(self.count('coverage_atoms'),0)
        self.assertEqual(self.j.snapshot('run').spent,10)
        self.assertEqual(self.j.history_metadata('run')['status'],'DETAILS_COLLECTED')
        self.assertEqual(self.j.history_metadata('never')['status'],'NOT_FOUND')
        self.assertEqual(self.j.collect_closed_run('run',outcome.eligible_after).status,'ALREADY_COLLECTED')
        self.assertEqual(self.count('cleanup_receipts'),1)

    def test_ret_c05_archive_recovery_preserves_identity_and_refuses_corruption(self):
        self.opened();self.collected();expected=self.j.snapshot('run')
        for table in ('identities','coverage_atoms','archive_observation_keys'):
            trigger=self.j._db.execute('SELECT sql FROM sqlite_master WHERE name=?',('protect_'+table+'_delete',)).fetchone()[0]
            self.j._db.execute('DROP TRIGGER protect_'+table+'_delete')
            self.j._db.execute(f'DELETE FROM {table}')
            self.j._db.execute(trigger)
        self.assertEqual(self.j.rebuild('run'),expected)
        self.assertEqual(self.j.events('run'),[])
        self.j.close();self.j=Journal(self.path,PROOF)
        self.assertEqual(self.j.rebuild('run'),expected)
        self.j._db.execute("INSERT INTO identities VALUES('source','extra','run','A','bad')")
        with self.assertRaises(JournalUnavailable):self.j.rebuild('run')

    def test_ret_c06_c07_new_final_both_orders_before_and_after_collection(self):
        for collected in (False,True):
            for closed_first in (False,True):
                with self.subTest(collected=collected,closed_first=closed_first):
                    path=Path(self.temp.name)/f'collision-{collected}-{closed_first}.db'
                    original=self.j;self.j=Journal(path,PROOF)
                    try:
                        a,_=self.opened('closed','A')
                        if collected:_,closed=self.collected('closed')
                        else:_,closed=self.close_run('closed')
                        self.assertEqual(self.j.import_opening(*import_data('active')).status,'IMPORTED')
                        b=paid(self.j,operation('active','B'))
                        late=observation([a],[12],event='new-E')
                        late=replace(late,receipts=(replace(late.receipts[0],source_event_id='new-E'),))
                        incoming=observation([b],[7],event='new-E')
                        incoming=replace(incoming,receipts=(replace(incoming.receipts[0],source_event_id='new-E'),))
                        if closed_first:
                            self.assertEqual(self.j.ingest_usage('closed',late).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
                            owner=self.j._observed_lookup('final',canonical(['fixture:source','new-E']))
                            self.assertEqual(owner['scope'],'closed')
                            self.assertEqual(self.j.ingest_usage('active',incoming).status,'CONFLICT')
                        else:
                            self.assertEqual(self.j.ingest_usage('active',incoming).status,'SETTLED')
                            owner=self.j._observed_lookup('final',canonical(['fixture:source','new-E']))
                            self.assertEqual(owner['scope'],'active')
                            self.assertEqual(self.j.ingest_usage('closed',late).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
                        self.assertEqual(self.j._observed_lookup('final',canonical(['fixture:source','new-E'])),owner)
                        self.assertEqual(self.j.snapshot('active').gate_status,'CONFLICT')
                        self.assertEqual(self.j.snapshot('closed').known_spent,10)
                        self.assertIsNone(self.j.snapshot('closed').spent)
                        count=self.count('financial_exceptions')
                        self.assertEqual(self.j.ingest_usage('closed',late).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
                        self.assertEqual(self.count('financial_exceptions'),count)
                        self.j.close();self.j=Journal(path,PROOF)
                        self.assertEqual(self.j.rebuild('closed').known_spent,10)
                        self.assertIsNone(self.j.snapshot('closed').spent)
                        if not collected:
                            self.assertEqual(self.j.collect_closed_run('closed',closed.eligible_after).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
                            self.assertTrue(self.j.events('closed'))
                    finally:
                        self.j.close();self.j=original

    def test_ret_c06_stream_and_ambiguous_batch_keys_remain_occupied(self):
        a,_=self.opened();self.collected()
        stream=observation([],[],event='late-stream',kind='STREAM')
        self.assertEqual(self.j.ingest_usage('run',stream).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
        self.assertEqual(self.j.import_opening(*import_data('active')).status,'IMPORTED')
        self.assertEqual(self.j.ingest_usage('active',stream).status,'CONFLICT')
        b=operation('active','B')
        batch=observation([a,b],[1,2],event='ambiguous')
        batch=replace(batch,receipts=tuple(replace(r,source_event_id='ambiguous-E') for r in batch.receipts))
        self.assertEqual(self.j.ingest_usage('run',batch).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
        owner=self.j._observed_lookup('final',canonical(['fixture:source','ambiguous-E']))
        self.assertEqual(len(owner['ambiguous']),2)
        trigger=self.j._db.execute("SELECT sql FROM sqlite_master WHERE name='protect_exception_identity_keys_delete'").fetchone()[0]
        self.j._db.execute('DROP TRIGGER protect_exception_identity_keys_delete')
        self.j._db.execute('DELETE FROM exception_identity_keys');self.j._db.execute(trigger)
        self.assertIsNone(self.j.rebuild('run').spent)
        self.assertEqual(self.j._observed_lookup('final',canonical(['fixture:source','ambiguous-E'])),owner)
        count=self.count('financial_exceptions')
        self.assertEqual(self.j.ingest_usage('run',batch).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
        self.assertEqual(self.count('financial_exceptions'),count)

    def test_ret_c08_collection_faults_roll_back_and_context_does_not_escape(self):
        self.opened();_,closed=self.close_run()
        for point in ('after_archive_seal','after_archive_indexes','after_delete_events','after_delete_scope_state','after_cleanup_receipt','before_commit'):
            with self.subTest(point=point):
                before=list(self.j._db.iterdump())
                def fail(stage):
                    if stage==point:raise RuntimeError('collection fault')
                self.j.fault_hook=fail
                with self.assertRaises(RuntimeError):self.j.collect_closed_run('run',closed.eligible_after)
                self.j.fault_hook=None
                self.assertEqual(list(self.j._db.iterdump()),before)
                self.assertFalse(self.j._retention_scopes)
        self.assertEqual(self.j.collect_closed_run('run',closed.eligible_after).status,'COLLECTED')

    def test_ret_c08_exception_key_head_quarantine_atomic_faults(self):
        a,_=self.opened();self.collected()
        self.assertEqual(self.j.import_opening(*import_data('active')).status,'IMPORTED')
        b=operation('active','B')
        obs=observation([a,b],[12,7],event='atomic')
        for point in ('after_financial_exception','after_exception_keys','after_exception_quarantine','before_commit'):
            with self.subTest(point=point):
                before=list(self.j._db.iterdump())
                def fail(stage):
                    if stage==point:raise RuntimeError('exception fault')
                self.j.fault_hook=fail
                with self.assertRaises(RuntimeError):self.j.ingest_usage('run',obs)
                self.j.fault_hook=None
                self.assertEqual(list(self.j._db.iterdump()),before)
                self.assertEqual(self.j.snapshot('active').gate_status,'READY')

    def test_ret_c11_logical_and_physical_results_are_separate(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import MaintenanceRequest
        a,_=self.opened()
        for n in range(8):
            self.j.ingest_usage('run',observation([],[],event='padding:'+str(n),kind='STREAM'))
        _,closed=self.close_run()
        now=closed.eligible_after
        from agent_lifecycle.accounting.contracts import utc_instant
        request=MaintenanceRequest(now,self.j.journal_identity,(utc_instant(now)+timedelta(seconds=10)).isoformat())
        result=self.j.maintenance(request)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(result['outcomes'][0]['logical_status'],'COLLECTED')
        self.assertEqual(result['outcomes'][0]['physical_status'],'NOT_REQUESTED')
        receipts=self.count('cleanup_receipts')
        result=self.j.reclaim_storage(request)
        self.assertEqual(result['status'],'RECLAIMED')
        self.assertLess(result['after_vacuum']['file_bytes'],result['before']['file_bytes'])
        self.assertEqual(self.count('cleanup_receipts'),receipts)
        self.assertEqual(self.j.snapshot('run').known_spent,10)
        self.assertEqual(self.j.maintenance(request)['outcomes'],[])


    def test_ret_c01_multiscope_roles_stale_unit_inventory_and_cancellation(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import RunClosure
        for scope_name in ('s1','s2'):
            scope,policy,imp=import_data(scope_name)
            scope=replace(scope,run_id='shared')
            self.assertEqual(self.j.import_opening(scope,policy,imp).status,'IMPORTED')
            for index,role in enumerate(('worker','task_review','implementation_audit','final_audit','coordinator','closeout'),1):
                op=replace(operation(scope_name,scope_name+':'+role,task='task' if index<=3 else None),run_id='shared',role=role)
                paid(self.j,op)
                self.assertEqual(self.j.ingest_usage(scope_name,observation([op],[index],event=op.operation_id)).status,'SETTLED')
            cancelled=replace(operation(scope_name,scope_name+':cancel'),run_id='shared')
            paid(self.j,cancelled)
            self.assertEqual(self.j.cancel_without_dispatch(scope_name,cancelled.operation_id,PROOF),'CANCELLED')
        now=(self.clock()+timedelta(seconds=1)).isoformat()
        inventory=tuple((s,self.j.snapshot(s).journal_revision) for s in ('s1','s2'))
        closure=RunClosure('closure:shared','shared','reportedTokens:fixture:v1',now,inventory,PROOF,PROOF)
        for value in (replace(closure,scope_revisions=inventory[:1]),replace(closure,unit_definition_id='other-unit')):
            before=list(self.j._db.iterdump())
            with self.assertRaises(JournalUnavailable):self.j.close_run(value,now)
            self.assertEqual(list(self.j._db.iterdump()),before)
        from agent_lifecycle.accounting.journal import RevisionConflict
        with self.assertRaises(RevisionConflict):
            self.j.close_run(replace(closure,scope_revisions=(('s1',0),inventory[1])),now)
        out=self.j.close_run(closure,now);self.assertEqual(out.status,'CLOSED')
        summary=self.j.closed_run('shared')['summary']
        self.assertEqual(summary['known_spent'],42)
        self.assertEqual(summary['roles'],dict(zip(('worker','task_review','implementation_audit','final_audit','coordinator','closeout'),(2,4,6,8,10,12))))
        self.assertEqual(self.j.collect_closed_run('shared',out.eligible_after).status,'COLLECTED')
        for scope in ('s1','s2'):
            self.assertEqual(self.j.rebuild(scope).spent,21)
            archive=self.j._retained('archive_records',scope)
            self.assertEqual(archive['protection']['cancellations'][0]['proof'],asdict(PROOF))
            self.assertNotIn('opening_import',archive['state'])
            def keys(value):
                if isinstance(value,dict):return set(value).union(*(keys(v) for v in value.values()))
                if isinstance(value,list):return set().union(*(keys(v) for v in value))
                return set()
            self.assertNotIn('raw',keys(archive))

    def test_ret_c01_unknown_untyped_and_clock_do_not_close(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import RunClosure

        from .test_journal import open_scope
        self.assertEqual(self.j.import_opening(*import_data('unknown',pending=None)).status,'IMPORTED')
        self.assertEqual(self.j.import_opening(*import_data('unknown-total',spent=None)).status,'IMPORTED')
        self.assertEqual(open_scope(self.j,'untyped'),'OPENED')
        for scope in ('unknown','unknown-total','untyped'):
            now=(self.clock()+timedelta(seconds=1)).isoformat()
            c=RunClosure('closure:'+scope,scope,'reportedTokens:fixture:v1',now,((scope,self.j.snapshot(scope).journal_revision),),PROOF,PROOF)
            before=list(self.j._db.iterdump())
            with self.assertRaises(JournalUnavailable):self.j.close_run(c,now)
            self.assertEqual(list(self.j._db.iterdump()),before)
        self.opened();now=self.clock().isoformat()
        c=RunClosure('clock','run','reportedTokens:fixture:v1','1970-01-01T00:00:00+00:00',(('run',self.j.snapshot('run').journal_revision),),PROOF,PROOF)
        with self.assertRaises(JournalUnavailable):self.j.close_run(c,now)
        with self.assertRaises(JournalUnavailable):self.j.close_run(replace(c,closed_at_utc='2099-01-01T00:00:00+00:00'),now)
        for instant in ('2026-09-21T12:00:00','2026-09-21T12:00:00+03:00','invalid'):
            with self.subTest(instant=instant),self.assertRaises(ValueError):replace(c,closed_at_utc=instant)

    def test_ret_c06_missing_projection_is_not_fresh_and_raw_origin_is_retained(self):
        a,_=self.opened();self.collected()
        late=observation([a],[12],event='new-E')
        self.assertEqual(self.j.ingest_usage('run',late).status,'ACCOUNTING_RECONCILIATION_REQUIRED')
        self.assertEqual(self.j.import_opening(*import_data('active')).status,'IMPORTED')
        b=paid(self.j,operation('active','B'))
        incoming=observation([b],[7],event='new-E')
        trigger=self.j._db.execute("SELECT sql FROM sqlite_master WHERE name='protect_exception_identity_keys_delete'").fetchone()[0]
        self.j._db.execute('DROP TRIGGER protect_exception_identity_keys_delete')
        self.j._db.execute('DELETE FROM exception_identity_keys');self.j._db.execute(trigger)
        before=self.j.snapshot('active')
        with self.assertRaises(JournalUnavailable):self.j.ingest_usage('active',incoming)
        self.assertEqual(self.j.snapshot('active'),before)
        self.j.rebuild('run')
        nested=observation([b],[7],event='outer-active',kind='STREAM')
        nested=replace(nested,receipts=(replace(nested.receipts[0],source_event_id='new-E'),))
        self.assertEqual(self.j.ingest_usage('active',nested).status,'CONFLICT')
        raw=self.j._observed_lookup('raw',canonical(['fixture:source','outer-active']))
        self.assertEqual(raw['scope'],'active')
        self.assertEqual(raw['digest'],digest(asdict(nested)))
        self.assertEqual(self.j.snapshot('run').known_spent,10)
        self.assertEqual(self.j.snapshot('active').known_spent,0)
        # A rejected candidate must not replace the first owner during reconstruction.
        key=canonical(['final',canonical(['fixture:source','new-E'])])
        original=self.j._retained('exception_identity_keys',key)
        original['binding']['scope']='active'
        sql=self.j._db.execute("SELECT sql FROM sqlite_master WHERE name='protect_exception_identity_keys_update'").fetchone()[0]
        self.j._db.execute('DROP TRIGGER protect_exception_identity_keys_update')
        self.j._db.execute('UPDATE exception_identity_keys SET payload=?,digest=? WHERE key=?',(canonical(original),digest(original),key))
        self.j._db.execute(sql)
        with self.assertRaises(JournalUnavailable):self.j.rebuild('run')

    def test_ret_c03_finite_maintenance_and_persisted_deadline(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import MaintenanceRequest, utc_instant
        self.opened('first','one');_,first=self.close_run('first')
        self.opened('second','two');_,second=self.close_run('second')
        due=max(first.eligible_after,second.eligible_after)
        request=MaintenanceRequest(due,self.j.journal_identity,(utc_instant(due)+timedelta(seconds=10)).isoformat(),candidate_limit=1)
        self.j.close();self.j=Journal(self.path,PROOF)
        self.assertEqual(self.j.closed_run('first')['eligible_after'],first.eligible_after)
        self.assertEqual(len(self.j.maintenance(request)['outcomes']),1)
        self.assertEqual(self.count('cleanup_receipts'),1)
        self.assertEqual(len(self.j.maintenance(request)['outcomes']),1)
        self.assertEqual(self.count('cleanup_receipts'),2)
        for kwargs in ({'retention_days':0},{'retention_days':True},{'candidate_limit':0}):
            with self.assertRaises(ValueError):replace(request,**kwargs)
        with self.assertRaises(JournalUnavailable):self.j.maintenance(replace(request,journal_identity='another'))



def retention_process(path, barrier, output, action, value, stage=None):
    from agent_lifecycle.accounting.journal import RevisionConflict
    def fault(point):
        if point == stage:
            os._exit(23)
    try:
        with Journal(path,PROOF,fault_hook=fault) as j:
            if barrier:barrier.wait(timeout=10)
            if action=='close':result=j.close_run(value,value.closed_at_utc).status
            elif action=='collect':result=j.collect_closed_run(value[0],value[1]).status
            elif action=='newscope':result=j.import_opening(*value).status
            elif action=='settle':result=j.ingest_usage(value[0],value[1]).status
            elif action=='vacuum':result=j.reclaim_storage(value)['status']
            else:raise ValueError(action)
            if output:output.put(result)
    except (JournalUnavailable,RevisionConflict):
        if output:output.put('UNAVAILABLE')


class RetentionProcessTests(unittest.TestCase):
    setUp = RetentionTests.setUp
    tearDown = RetentionTests.tearDown
    opened = RetentionTests.opened
    close_run = RetentionTests.close_run
    collected = RetentionTests.collected
    count = RetentionTests.count
    def race(self, actions):
        ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(len(actions));out=ctx.Queue()
        workers=[ctx.Process(target=retention_process,args=(str(self.path),barrier,out,action,value)) for action,value in actions]
        for p in workers:p.start()
        for p in workers:
            p.join(15)
            if p.is_alive():p.kill();p.join();self.fail('bounded retention race timed out')
            self.assertEqual(p.exitcode,0)
        return [out.get(timeout=2) for _ in workers]

    def test_ret_c08_actual_process_death_and_repeat_collection(self):
        self.opened();_,closed=self.close_run();before=self.j.snapshot('run')
        ctx=multiprocessing.get_context('spawn')
        for point in ('after_archive_seal','after_delete_events','after_cleanup_receipt'):
            p=ctx.Process(target=retention_process,args=(str(self.path),None,None,'collect',('run',closed.eligible_after),point))
            p.start();p.join(15)
            if p.is_alive():p.kill();p.join();self.fail('bounded collection kill witness timed out')
            self.assertEqual(p.exitcode,23)
            self.assertEqual(self.j.rebuild('run'),before)
            self.assertEqual(self.count('archive_records'),0)
            self.assertEqual(self.count('cleanup_receipts'),0)
        self.assertEqual(sorted(self.race([('collect',('run',closed.eligible_after))]*2)),['ALREADY_COLLECTED','COLLECTED'])
        self.assertEqual(self.j.rebuild('run'),before)

    def test_ret_c08_close_newscope_and_final_settlement_races(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import RunClosure
        self.opened();now=(self.clock()+timedelta(seconds=1)).isoformat()
        c=RunClosure('race-close','run','reportedTokens:fixture:v1',now,(('run',self.j.snapshot('run').journal_revision),),PROOF,PROOF)
        self.assertEqual(sorted(self.race([('close',c)]*2)),['ALREADY_CLOSED','CLOSED'])
        self.opened('race-new','N');now=(self.clock()+timedelta(seconds=1)).isoformat()
        c=RunClosure('close-new','race-new','reportedTokens:fixture:v1',now,(('race-new',self.j.snapshot('race-new').journal_revision),),PROOF,PROOF)
        scope,policy,imp=import_data('new-member');scope=replace(scope,run_id='race-new')
        result=self.race([('close',c),('newscope',(scope,policy,imp))])
        self.assertIn(sorted(result),[['CLOSED','CLOSED'],['IMPORTED','UNAVAILABLE']])
        self.assertEqual(self.j.import_opening(*import_data('race-final')).status,'IMPORTED')
        a=paid(self.j,operation('race-final','F'));obs=observation([a],[13],event='final-race')
        now=(self.clock()+timedelta(seconds=1)).isoformat()
        c=RunClosure('close-final','race-final','reportedTokens:fixture:v1',now,(('race-final',self.j.snapshot('race-final').journal_revision),),PROOF,PROOF)
        self.assertEqual(sorted(self.race([('close',c),('settle',('race-final',obs))])),['SETTLED','UNAVAILABLE'])
        self.assertIsNone(self.j.closed_run('race-final'))
        self.assertEqual(self.j.snapshot('race-final').known_spent,13)
        self.close_run('race-final')

    def test_ret_c11_physical_busy_interrupt_and_process_death(self):
        from datetime import timedelta

        from agent_lifecycle.accounting.contracts import MaintenanceRequest, utc_instant
        self.opened()
        for n in range(20):self.j.ingest_usage('run',observation([],[],event='physical:'+str(n),kind='STREAM'))
        _,closed=self.collected();counts=self.count('cleanup_receipts');before=self.j.snapshot('run')
        request=MaintenanceRequest(closed.eligible_after,self.j.journal_identity,
                                   (utc_instant(closed.eligible_after)+timedelta(seconds=10)).isoformat())
        reader=sqlite3.connect(self.path,isolation_level=None)
        try:
            reader.execute('BEGIN');reader.execute('SELECT * FROM archive_records').fetchall()
            result=self.j.reclaim_storage(request)
            self.assertEqual(result['status'],'NEEDS_STORAGE_MAINTENANCE')
            self.assertEqual(result['receipt_status'],'UNAVAILABLE')
        finally:reader.execute('ROLLBACK');reader.close()
        ctx=multiprocessing.get_context('spawn')
        p=ctx.Process(target=retention_process,args=(str(self.path),None,None,'vacuum',request,'during_vacuum'))
        p.start();p.join(15)
        if p.is_alive():p.kill();p.join();self.fail('bounded physical kill witness timed out')
        self.assertEqual(p.exitcode,23)
        self.assertEqual(self.j.rebuild('run'),before)
        tiny=replace(request,work_deadline_utc=(utc_instant(request.now_utc)+timedelta(microseconds=1)).isoformat())
        self.assertEqual(self.j.reclaim_storage(tiny)['status'],'NEEDS_STORAGE_MAINTENANCE')
        result=self.j.reclaim_storage(request)
        self.assertEqual(result['status'],'RECLAIMED')
        self.assertEqual(self.count('cleanup_receipts'),counts)
        self.assertEqual(self.j.snapshot('run'),before)
        print('RETENTION_PHYSICAL_EVIDENCE '+json.dumps(result,sort_keys=True))


class StorageV3RetentionMigrationTests(unittest.TestCase):
    """RET-C09: independently captured v3 data, never regenerated by v4."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'golden.db'
        data = json.loads((Path(__file__).parent / 'fixtures/release_216_accounting.json').read_text(encoding='utf-8'))
        self.golden = data['storageV3Golden']

    def tearDown(self):
        self.temp.cleanup()

    def restore(self, data=None, name='golden.db'):
        return StorageMigrationTests.restore(self, data, name)

    def test_v3_rows_and_pending_qualification_preserved(self):
        self.restore()
        with self.assertRaises(JournalUnavailable):
            Journal(self.path, PROOF)
        Journal.migrate_v3(self.path, PROOF)
        with Journal(self.path, PROOF) as j:
            for table, value in self.golden['tables'].items():
                expected = [[1, STORAGE_SCHEMA_VERSION]] if table == 'schema_metadata' else value['rows']
                self.assertEqual(sorted([list(r) for r in j._db.execute(f'SELECT * FROM {table}')]), sorted(expected))
            for scope, projection in self.golden['expectedProjections'].items():
                self.assertEqual(asdict(j.snapshot(scope)), projection)
            self.assertEqual(j.snapshot('closed-candidate').spent, 38)
            self.assertEqual(j.snapshot('claimed').active_reservations, 12)
            self.assertEqual(j._load('claimed')[0]['operations']['C']['state'], 'RESERVED')
            self.assertIsNone(j.snapshot('unknown').spent)
            self.assertEqual(j.rebuild('closed-candidate').spent, 38)
            self.assertEqual(j._db.execute('SELECT COUNT(*) FROM run_closures').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                j._db.execute("DELETE FROM events WHERE scope='closed-candidate'")

    def test_v3_migration_faults_and_already_open_writer(self):
        for point in ('before_version', 'after_version'):
            with self.subTest(point=point):
                path = self.restore(name=point + '.db')
                before = path.read_bytes()
                def fail(at):
                    if at == point:
                        raise RuntimeError('migration fault')
                with self.assertRaises(RuntimeError):
                    Journal.migrate_v3(path, PROOF, fault_hook=fail)
                self.assertEqual(path.read_bytes(), before)
        self.restore()
        old = sqlite3.connect(self.path, isolation_level=None)
        old.create_function('alk_storage_writer_version', 0, lambda: 3)
        try:
            event = list(old.execute('SELECT * FROM events LIMIT 1').fetchone())
            Journal.migrate_v3(self.path, PROOF)
            before = list(old.iterdump())
            old.execute('BEGIN IMMEDIATE')
            old.execute("INSERT INTO identities VALUES('fixture','stale-v3','claimed','C','old')")
            event[0], event[2], event[4] = 'stale-v3:event', 999, 'stale-v3:tx'
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'incompatible storage writer'):
                old.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)', event)
            old.execute('ROLLBACK')
            self.assertEqual(list(old.iterdump()), before)
        finally:
            old.close()

    def test_v3_invalid_inputs_refused_without_repair_or_conversion(self):
        for corruption in ('identity', 'projection', 'delta', 'schema', 'wal'):
            with self.subTest(corruption=corruption):
                data = copy.deepcopy(self.golden)
                if corruption == 'identity':
                    data['tables']['identities']['rows'] = [r for r in data['tables']['identities']['rows']
                                                          if not (r[0] == 'claim' and r[2] == 'claimed')]
                elif corruption == 'projection':
                    data['tables']['scope_state']['rows'][0][1] += 1
                elif corruption == 'delta':
                    event = next(r for r in data['tables']['events']['rows'] if 'state_delta' in r[6])
                    value = json.loads(event[6]); value['state_delta']['result_digest'] = '0' * 64
                    event[6], event[7] = canonical(value), digest(value)
                elif corruption == 'schema':
                    data['schema'] = [r for r in data['schema'] if r['name'] != 'require_storage_writer']
                path = self.restore(data, corruption + '.db')
                db = sqlite3.connect(path)
                try:
                    if corruption == 'wal':
                        db.execute('PRAGMA journal_mode=WAL')
                    before = list(db.iterdump())
                    mode = db.execute('PRAGMA journal_mode').fetchone()[0]
                    with self.assertRaises(JournalUnavailable):
                        Journal.migrate_v3(path, PROOF)
                    self.assertEqual(list(db.iterdump()), before)
                    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], mode)
                finally:
                    db.close()


class StorageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'golden.db'
        data = json.loads((Path(__file__).parent / 'fixtures/release_216_accounting.json').read_text(encoding='utf-8'))
        self.golden = data['storageV2Golden']

    def tearDown(self):
        self.temp.cleanup()

    def restore(self, data=None, name='golden.db'):
        path = Path(self.temp.name) / name
        data = data or self.golden
        with closing(sqlite3.connect(path)) as db, db:
            for row in data['schema']:
                if row['type'] == 'table':
                    db.execute(row['sql'])
            for table, value in data['tables'].items():
                placeholders = ','.join('?' for _ in value['columns'])
                db.executemany(f'INSERT INTO {table} VALUES({placeholders})', value['rows'])
            for row in data['schema']:
                if row['type'] == 'trigger':
                    db.execute(row['sql'])
        return path

    def legacy_v2_schema(self, db):
        # Only synthetic scenarios: bind their rows to the original v2 schema.
        # Do not regenerate either captured golden or modify a customer journal.
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
            db.execute('DROP TRIGGER ' + row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if row[0] not in self.golden['tables']:
                db.execute('DROP TABLE ' + row[0])
        for row in self.golden['schema']:
            if row['type'] == 'trigger':
                db.execute(row['sql'])
        db.execute('UPDATE schema_metadata SET version=2')

    def rows(self, db):
        return {table: sorted([list(row) for row in db.execute(f'SELECT * FROM {table}')])
                for table in self.golden['tables']}

    def test_storage_review_f01_missing_claim_permit_cannot_be_reused(self):
        data = copy.deepcopy(self.golden)
        data['tables']['identities']['rows'] = [row for row in data['tables']['identities']['rows']
            if not (row[0] in ('permit', 'claim') and row[1] == canonical('claimed:permit:C'))]
        self.restore(data)
        before = self.path.read_bytes()
        try:
            Journal.migrate_v2(self.path, PROOF)
        except JournalUnavailable:
            self.assertEqual(self.path.read_bytes(), before)
            return
        from agent_lifecycle.accounting.journal import _operation
        with Journal(self.path, PROOF) as j:
            original = _operation(j._load('claimed')[0]['operations']['C']['binding'])
            other = replace(original, operation_id='D', dispatch_key='dispatch:D')
            reserved = j.reserve(other)
            claimed = j.claim('claimed', 'D', other.binding_digest, 'another-claim')
            self.fail(f'Corrupt journal migrated; reused C permit for D: {reserved}/{claimed}')

    def test_storage_review_f02_wal_refusal_preserves_mode_and_data(self):
        for case in ('unknown_version', 'corrupt_projection', 'valid_v2'):
            with self.subTest(case=case):
                path = self.restore(name='wal-' + case + '.db')
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
                    if case == 'unknown_version':
                        db.execute('UPDATE schema_metadata SET version=99')
                    elif case == 'corrupt_projection':
                        db.execute('UPDATE scope_state SET revision=99')
                db.close()
                before = path.read_bytes()
                with self.assertRaises(JournalUnavailable):
                    Journal.migrate_v2(path, PROOF)
                self.assertEqual(path.read_bytes(), before)
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_storage_review_f01_all_claimed_key_bindings_are_required(self):
        for kind in ('operation', 'dispatch', 'permit', 'claim'):
            for corruption in ('missing', 'scope', 'owner', 'digest'):
                with self.subTest(kind=kind, corruption=corruption):
                    data = copy.deepcopy(self.golden)
                    rows = data['tables']['identities']['rows']
                    row = next(r for r in rows if r[0] == kind and r[2:4] == ['claimed', 'C'])
                    if corruption == 'missing': rows.remove(row)
                    else: row[{'scope': 2, 'owner': 3, 'digest': 4}[corruption]] = 'wrong'
                    path = self.restore(data, name=kind + '-' + corruption + '.db')
                    before = path.read_bytes()
                    with self.assertRaises(JournalUnavailable):
                        Journal.migrate_v2(path, PROOF)
                    self.assertEqual(path.read_bytes(), before)

    def test_storage_review_f01_ordinary_open_final_overflow_identity_inventory(self):
        from .test_journal import open_scope
        path = Path(self.temp.name) / 'ordinary.db'
        with Journal(path, PROOF) as j:
            open_scope(j, covered=(('fixture:source', 'covered-before-opening'),))
            a, b = operation(name='settled'), operation(name='overflow')
            for op, amount in ((a, 80), (b, MAX_INTEGER)):
                paid(j, op)
                j.record_settlement(receipt(op, amount))
            self.assertEqual(j.events('run')[-1]['kind'], 'OVERFLOW')
            # These are unchanged P01 event forms inside a P02-table storage schema.
            self.assertTrue(all('state_delta' not in json.loads(e['payload']) for e in j.events('run')))
            before_projection = j.snapshot('run')
            self.legacy_v2_schema(j._db)
            keys = [tuple(row) for row in j._db.execute('SELECT * FROM identities')]
        old_bytes = path.read_bytes()
        for index, key in enumerate(keys):
            with self.subTest(kind=key[0], key=key[1]):
                corrupted = Path(self.temp.name) / f'ordinary-key-{index}.db'
                corrupted.write_bytes(old_bytes)
                with closing(sqlite3.connect(corrupted)) as db, db:
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='protect_identities_delete'").fetchone()[0]
                    db.execute('DROP TRIGGER protect_identities_delete')
                    db.execute('DELETE FROM identities WHERE kind=? AND key=?', key[:2])
                    db.execute(trigger)
                before = corrupted.read_bytes()
                with self.assertRaises(JournalUnavailable):
                    Journal.migrate_v2(corrupted, PROOF)
                self.assertEqual(corrupted.read_bytes(), before)
        Journal.migrate_v2(path, PROOF)
        with Journal(path, PROOF) as j:
            self.assertEqual(j.snapshot('run'), before_projection)
            self.assertEqual(j.rebuild('run'), before_projection)

    def test_storage_review_f01_rejected_opening_shells_preserve_no_keys(self):
        from agent_lifecycle.accounting.journal import _apply

        from .test_journal import open_scope
        path = Path(self.temp.name) / 'rejected-opening.db'
        with Journal(path, PROOF) as j:
            covered = (('fixture:source', 'shared-opening-source'),)
            self.assertEqual(open_scope(j, 'owner', covered=covered), 'OPENED')
            self.assertEqual(open_scope(j, 'conflicted', covered=covered), 'CONFLICT')
            missing_profile_charge = replace(history(operation('shell'), 10), profile_id='unqualified')
            scope, policy, imp = import_data(scope='shell', historical=(missing_profile_charge,), spent=10)
            result = j.import_opening(scope, policy, imp)
            self.assertEqual(result.status, 'UNAVAILABLE')
            self.assertEqual(j.events('shell')[0]['kind'], 'OPEN')
            self.assertFalse(any(row[0] in ('conflicted', 'shell') for row in j._db.execute('SELECT scope FROM identities')))
            for opening_scope in ('owner', 'conflicted', 'shell'):
                replayed, revision, _, declared = j._live_facts(opening_scope)
                saved, saved_revision = j._load(opening_scope)
                self.assertEqual((replayed, revision), (saved, saved_revision))
                self.assertEqual(bool(declared), opening_scope == 'owner')
            # Materialize this new rejection scenario as the legacy representation;
            # the captured golden v2 fixture is untouched and is never regenerated.
            trigger = j._db.execute("SELECT sql FROM sqlite_master WHERE name='protect_events_update'").fetchone()[0]
            j._db.execute('DROP TRIGGER protect_events_update')
            state = None
            for event in j.events('shell'):
                payload = json.loads(event['payload'])
                state = _apply(state, event['kind'], payload)
                if 'state_delta' in payload:
                    del payload['state_delta']; payload['after'] = copy.deepcopy(state)
                    j._db.execute('UPDATE events SET payload=?,digest=? WHERE event_id=?',
                                  (canonical(payload), digest(payload), event['event_id']))
            j._db.execute(trigger)
            self.legacy_v2_schema(j._db)
            before = self.rows(j._db)
        Journal.migrate_v2(path, PROOF)
        with Journal(path, PROOF) as j:
            before['schema_metadata'] = [[1, STORAGE_SCHEMA_VERSION]]
            self.assertEqual(self.rows(j._db), before)
            self.assertEqual(j.snapshot('conflicted').gate_status, 'CONFLICT')
            self.assertEqual(j.snapshot('shell').gate_status, 'INCOMPLETE')

    def test_storage_v2_golden_preservation_and_mixed_replay(self):
        self.restore()
        with self.assertRaises(JournalUnavailable):
            Journal(self.path, PROOF)
        Journal.migrate_v2(self.path, PROOF)
        with Journal(self.path, PROOF) as j:
            expected = {table: sorted(value['rows']) for table, value in self.golden['tables'].items()}
            expected['schema_metadata'] = [[1, STORAGE_SCHEMA_VERSION]]
            self.assertEqual(self.rows(j._db), expected)
            for scope, projection in self.golden['expectedProjections'].items():
                self.assertEqual(json.loads(canonical(asdict(j.snapshot(scope)))), projection)
            # Pure migration must not convert a durable unfinalized claim to UNAVAILABLE.
            self.assertEqual(j._load('claimed')[0]['operations']['C']['state'], 'RESERVED')
            self.assertEqual(len(j.events('claimed')), 3)
            from agent_lifecycle.accounting.journal import _operation
            op = _operation(j._load('claimed')[0]['operations']['C']['binding'])
            obs = observation([op], [8], event='post-migration:C')
            self.assertEqual(j.ingest_usage('claimed', obs).status, 'SETTLED')
            self.assertEqual(j.ingest_usage('claimed', obs).status, 'ALREADY_SETTLED')
            payload = json.loads(j.events('claimed')[-1]['payload'])
            self.assertNotIn('after', payload)
            self.assertEqual(payload['state_delta']['codec'], 'ALK_STATE_DELTA_V1')
            self.assertEqual(j.snapshot('claimed').spent, 8)
            before = j.snapshot('claimed')
            self.assertEqual(j.rebuild('claimed'), before)
            # The other migrated scope retains known28, unknown total, protected12 and reservation10.
            before = j.snapshot('golden')
            self.assertEqual(j.rebuild('golden'), before)
            actual = self.rows(j._db)
            for table in ('events', 'identities', 'coverage_atoms', 'corroborating_finals'):
                for row in expected[table]:
                    self.assertIn(row, actual[table])
            self.assertEqual(len(j._load('golden')[0]['accepted_finals']), 2)
            self.assertEqual(len(j._load('golden')[0]['aliases']), 1)
        with Journal(self.path, PROOF) as j:
            self.assertEqual(j.rebuild('claimed').spent, 8)
            before = list(j._db.iterdump())
        with self.assertRaises(JournalUnavailable):
            Journal.migrate_v2(self.path, PROOF)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(list(db.iterdump()), before)

    def test_storage_v2_migration_faults_and_stale_open_connection(self):
        for point in ('before_version', 'after_version'):
            with self.subTest(point=point):
                path = self.restore(name=point + '.db')
                before_bytes = path.read_bytes()
                def fault(at):
                    if at == point:
                        raise RuntimeError('injected migration failure')
                with self.assertRaises(RuntimeError):
                    Journal.migrate_v2(path, PROOF, fault_hook=fault)
                self.assertEqual(path.read_bytes(), before_bytes)
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertEqual(self.rows(db), {k: sorted(v['rows']) for k, v in self.golden['tables'].items()})
                    self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='require_storage_writer'").fetchone())
        self.restore()
        old = sqlite3.connect(self.path, isolation_level=None)
        try:
            event = list(old.execute('SELECT * FROM events LIMIT 1').fetchone())
            Journal.migrate_v2(self.path, PROOF)
            before = list(old.iterdump())
            old.execute('BEGIN IMMEDIATE')
            old.execute("INSERT INTO identities VALUES('fixture','stale','claimed','C','old')")
            event[0], event[2], event[4] = 'stale:event', 999, 'stale:tx'
            with self.assertRaisesRegex(sqlite3.OperationalError, 'alk_storage_writer_version'):
                old.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)', event)
            old.execute('ROLLBACK')
            self.assertEqual(list(old.iterdump()), before)
        finally:
            old.close()

    def test_storage_v2_corruption_refused_without_repair(self):
        cases = ('partial_schema', 'altered_schema', 'unknown_version', 'event_json', 'event_digest',
                 'event_order', 'unknown_kind', 'compact_in_v2', 'mixed_payload', 'projection_state',
                 'projection_revision', 'missing_projection', 'index_digest', 'index_owner',
                 'missing_index', 'extra_index', 'identity_binding', 'missing_identity',
                 'baseline_data', 'baseline_revision', 'extra_baseline')
        for case in cases:
            with self.subTest(case=case):
                data = copy.deepcopy(self.golden)
                tables = data['tables']
                event = next(row for row in tables['events']['rows'] if row[5] == 'IMPORT_OPENING')
                if case == 'partial_schema':
                    data['schema'] = [row for row in data['schema'] if row['name'] != 'protect_events_update']
                elif case == 'altered_schema':
                    next(row for row in data['schema'] if row['name'] == 'protect_events_update')['sql'] = (
                        "CREATE TRIGGER protect_events_update BEFORE UPDATE ON events BEGIN SELECT 1; END")
                elif case == 'unknown_version': tables['schema_metadata']['rows'][0][1] = 99
                elif case == 'event_json': event[6] = '{invalid'
                elif case == 'event_digest': event[7] = '0' * 64
                elif case == 'event_order': event[2] = 100
                elif case == 'unknown_kind': event[5] = 'UNKNOWN'
                elif case in ('compact_in_v2', 'mixed_payload'):
                    from agent_lifecycle.accounting.journal import _state_delta
                    value = json.loads(event[6]); value['state_delta'] = _state_delta(None, value['after'])
                    if case == 'compact_in_v2': del value['after']
                    event[6], event[7] = canonical(value), digest(value)
                elif case == 'projection_state':
                    row = tables['scope_state']['rows'][0]
                    value = json.loads(row[2]); value['overhead'] = True
                    row[2] = canonical(value)
                elif case == 'projection_revision': tables['scope_state']['rows'][0][1] += 1
                elif case == 'missing_projection': tables['scope_state']['rows'].pop()
                elif case == 'index_digest': tables['source_profiles']['rows'][0][3] = '0' * 64
                elif case == 'index_owner': tables['source_profiles']['rows'][0][2] = 'wrong'
                elif case == 'missing_index': tables['source_profiles']['rows'].pop()
                elif case == 'extra_index':
                    row = list(tables['source_profiles']['rows'][0]); row[0] = 'extra'
                    tables['source_profiles']['rows'].append(row)
                elif case == 'identity_binding':
                    next(row for row in tables['identities']['rows'] if row[0] == 'opening')[4] = '0' * 64
                elif case == 'missing_identity':
                    tables['identities']['rows'] = [row for row in tables['identities']['rows'] if row[0] != 'opening']
                elif case == 'baseline_data': tables['source_baselines']['rows'][0][3] = '{}'
                elif case == 'baseline_revision': tables['source_baselines']['rows'][0][2] = 0
                elif case == 'extra_baseline':
                    row = list(tables['source_baselines']['rows'][0]); row[1] = 'extra'
                    tables['source_baselines']['rows'].append(row)
                path = self.restore(data, name=case + '.db')
                before_bytes = path.read_bytes()
                with self.assertRaises(JournalUnavailable):
                    Journal.migrate_v2(path, PROOF)
                self.assertEqual(path.read_bytes(), before_bytes)


if __name__ == '__main__':
    unittest.main()
