# CLI error contract

The root `agent-lifecycle` command returns a JSON error envelope with exit code
`2` when an expected operation cannot be completed. The envelope uses
`agent-lifecycle-error.v1` and does not expose tracebacks, exception text,
absolute paths or input contents.

The Russian version is available in [русской документации](../ru/reference/cli-errors.md).

## Stable error codes

| Code | Meaning |
| --- | --- |
| `cli-io-error` | An input or output file could not be read or written. |
| `cli-invalid-encoding` | An input file is not valid UTF-8 text. |
| `cli-invalid-json` | An input file is not valid JSON. |
| `cli-json-depth-exceeded` | JSON nesting exceeds the supported safety limit. |
| `cli-unexpected-error` | An unexpected internal failure reached the root boundary. |

Existing domain errors retain their own stable code and message contract. The
root boundary only converts exceptions that do not already implement
`LifecycleError`.

## Example

```json
{"code":"cli-io-error","details":{},"message":"CLI input or output could not be read or written","schemaVersion":"agent-lifecycle-error.v1"}
```

Machine clients should branch on `code` and `schemaVersion`, not on the human
message. Command-line syntax errors produced by `argparse` retain normal
`SystemExit` behavior. `KeyboardInterrupt` and `SystemExit` raised by the
application are also preserved and are never converted into a lifecycle error.
