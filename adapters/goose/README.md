# Goose Adapter

This adapter is an EXPERIMENTAL Agent Lifecycle Kit projection for the Goose
host. It declares ACP as a neutral host capability and keeps lifecycle
semantics in ALK core.

The descriptor is validated offline. A supported ACP declaration still requires
a host probe before use; missing executable, failed probe, or invalid invocation
contract must fail closed.
