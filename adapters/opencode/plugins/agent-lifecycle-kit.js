// OpenCode's legacy plugin loader consumes exported functions.  ALK keeps its
// lifecycle semantics in the shared core and skills, so this projection only
// establishes a valid, side-effect-free host plugin boundary.
export const AgentLifecycleKit = async () => ({});

AgentLifecycleKit.alkMetadata = Object.freeze({
  name: "agent-lifecycle-kit",
  maturity: "VERIFIED",
  descriptor: "../adapter.descriptor.json",
  unsupportedOperationPolicy: "fail-closed",
  coreSemantics: "delegated-to-agent-lifecycle-core"
});
