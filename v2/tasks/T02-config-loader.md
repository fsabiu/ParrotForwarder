# T02 - Config loader

**Phase**: 0
**Depends on**: T01
**Estimated effort**: S

## Goal

Implement the layered config loader defined in [../specs/02-config.md](../specs/02-config.md). No integration with the runtime yet - just the loader + tests.

## Acceptance criteria

- `parrot_forwarder/config.py` exposes `load_config(path: Optional[Path], env: Mapping[str, str], cli_overrides: dict) -> Config`.
- `Config` is a pydantic model mirroring the schema in the spec. All fields typed; validation errors reference the field path.
- Precedence: defaults < yaml < env < cli (cli wins).
- `reloadable` fields identified; `reload_config(old, new)` returns a `ReloadResult(applied, rejected)` indicating which changes are accepted.
- Example `config.yaml` committed at `config.yaml.example` with every field and a brief comment.

## Files touched

- `src/parrot_forwarder/config.py`
- `tests/test_config.py`
- `config.yaml.example`

## How to verify

```bash
pytest tests/test_config.py -v
```

Tests from [../specs/02-config.md#tests-required](../specs/02-config.md#tests-required) must all pass.

## Notes

- Use pydantic v2 features (`model_config`, `Field(alias=...)`).
- Env var parsing: split `PARROT_FORWARDER_` prefix, lowercase, split `__` into nesting levels. Coerce via pydantic validators.
- Do not read files at module import. `load_config` must be callable with no side effects beyond the provided inputs.
