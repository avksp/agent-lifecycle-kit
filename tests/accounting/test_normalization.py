"""Qualified fixture witnesses; none qualify a real provider or execution host."""
import hashlib
import json
from dataclasses import asdict, replace
import unittest

from agent_lifecycle.accounting.contracts import (
    CoverageAtom, CounterMembership, EvidenceRef, SourceProfile, UsageObservation, canonical,
)
from agent_lifecycle.accounting.normalization import (
    UsageConflict, UsageUnavailable, coverage_digest, normalize,
)
from .test_journal import PROOF, operation, receipt


def profile(scope='run', cumulative=False):
    return SourceProfile('fixture:usage:v1', scope, 'fixture:source', 'fixture:v1',
                         'reportedTokens:fixture:v1', 'fixture:paid-unit:v1',
                         'CUMULATIVE' if cumulative else 'OPERATION_FINAL', PROOF, fixture_only=True)


def atom(op, amount, *, epoch='epoch:1', name=None):
    return CoverageAtom('fixture:paid-unit:v1', epoch, name or op.budget_scope_id+':'+op.operation_id,
                        op.operation_id, op.binding_digest, op.task_id, op.role, amount, PROOF)


def observation(ops, amounts, *, event='leaf', kind='FINAL', sequence=1,
                total=None, atoms=None, epoch='epoch:1', components=None, intervals=None):
    atoms = tuple(atoms) if atoms is not None else tuple(atom(o,a,epoch=epoch) for o,a in zip(ops,amounts))
    total = sum(amounts) if total is None else total
    raw = canonical({'event':event,'kind':kind,'total':total,'operations':[o.operation_id for o in ops]})
    raw_ref = EvidenceRef('fixture:raw:'+event,hashlib.sha256(raw.encode()).hexdigest())
    finals=[]
    if kind!='PARENT':
        for op,amount in zip(ops,amounts):
            partition=tuple(a for a in atoms if a.operation_id==op.operation_id)
            value=receipt(op,amount,event=event if len(ops)==1 else event+':'+op.operation_id)
            finals.append(replace(value,receipt_id='receipt:'+event+':'+op.operation_id,
                                  coverage=EvidenceRef('fixture:partition',coverage_digest(partition)),
                                  raw_evidence=raw_ref))
    # Explicit fixture-source ordering assertion, never inferred by production code.
    memberships=tuple(CounterMembership(*a.key, *(intervals[i] if intervals is not None
                          else (max(0,sequence-1),sequence)), PROOF)
                      for i,a in enumerate(atoms)) if sequence else ()
    return UsageObservation('fixture:usage:v1',event,epoch,sequence,kind,total,atoms,
                            tuple(finals),raw,raw_ref,components or {},memberships)


class NormalizationTests(unittest.TestCase):
    def test_v01_subsets_types_and_authoritative_zero(self):
        op=operation(); p=profile()
        obs=observation([op],[100],components={'input':80,'cached':60,'output':20,'reasoning':10})
        self.assertEqual(normalize(p,obs,{'operations':{'op':op}})['amount'],100)
        zero=observation([op],[0]); self.assertEqual(normalize(p,zero,{'operations':{'op':op}})['amount'],0)
        with self.assertRaises(UsageUnavailable): normalize(p,replace(zero,total=None),{'operations':{'op':op}})
        for invalid in (True,1.5,-1):
            with self.subTest(value=invalid),self.assertRaises(ValueError):replace(obs,total=invalid)
        with self.assertRaises(UsageConflict): normalize(p,replace(obs,components={'input':80,'output':20,'cached':81}),{'operations':{'op':op}})
        with self.assertRaises(ValueError):replace(p,unit_definition_id='real:tokens')
        with self.assertRaises(UsageUnavailable):normalize(p,replace(obs,receipts=(replace(obs.receipts[0],attestation=EvidenceRef('unqualified','b'*64)),)),{'operations':{'op':op}})
        with self.assertRaises(ValueError):replace(obs,raw=obs.raw+' ')

    def test_v02_cumulative_delta_and_boundaries(self):
        a,b=operation(name='A'),operation(name='B');p=profile(cumulative=True)
        baseline={'epoch':'epoch:1','sequence':0,'total':100,'checkpoints':{'0':100},
                  'frontier':{'origin_sequence':0,'precutoff_atoms':[],'members':{}}}
        first=observation([a],[30],event='130',kind='SNAPSHOT',total=130,sequence=1)
        c=normalize(p,first,{'operations':{'A':a},'baseline':baseline})
        self.assertEqual(c['amount'],30)
        second=observation([b],[30],event='160',kind='SNAPSHOT',total=160,sequence=2)
        d=normalize(p,second,{'operations':{'B':b},'baseline':c['baseline']})
        self.assertEqual(d['amount'],30)
        late=normalize(p,first,{'operations':{'A':a},'baseline':d['baseline']})
        self.assertTrue(late['late']);self.assertIsNone(late['baseline'])
        for obs,base in ((replace(second,total=5,sequence=3),d['baseline']),(second,None),
                         (replace(second,epoch='reset'),d['baseline'])):
            with self.subTest(obs=obs.source_event_id),self.assertRaises((UsageUnavailable,UsageConflict)):
                normalize(p,obs,{'operations':{'B':b},'baseline':base})

    def test_v03_parent_derivation_and_stream(self):
        a,b=operation(name='A'),operation(name='B');p=profile()
        obs=observation([a,b],[60,40],event='parent',kind='PARENT')
        result=normalize(p,obs,{'operations':{'A':a,'B':b}})
        self.assertEqual([f['receipt']['reported_tokens'] for f in result['finals']],[60,40])
        self.assertEqual(len({f['receipt']['source_event_id'] for f in result['finals']}),2)
        with self.assertRaises(UsageUnavailable):normalize(p,replace(obs,atoms=()),{'operations':{'A':a,'B':b}})
        with self.assertRaises(UsageUnavailable):normalize(p,replace(obs,kind='STREAM'),{'operations':{'A':a,'B':b}})


if __name__=='__main__':unittest.main()
