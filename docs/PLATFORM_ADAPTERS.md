# Platform adapter architecture

The publication pipeline separates shared orchestration from official platform API code.

## Layers

- `PlatformAdapter` defines the asynchronous publishing and metrics contract.
- `PlatformRegistry` maps normalized platform names to adapter factories.
- `Publisher` validates local media, invokes an adapter, and records a durable publication receipt.
- Platform modules, such as `platforms/youtube.py`, own API-specific credentials, request bodies, and responses.

The CLI and continuous worker still expose the existing YouTube commands, but both now use the shared registry and publication service.

## Adding a platform

1. Implement `PlatformAdapter` in `social_bot/platforms/<platform>.py`.
2. Use only the platform's official API and OAuth flow.
3. Register the adapter factory in the application composition layer.
4. Add platform-specific queue validation, cooldown rules, and tests.
5. Keep dry-run behavior as the default and require explicit live configuration.

Example:

```python
registry = PlatformRegistry()
registry.register("example", ExampleOfficialApiAdapter)
adapter = registry.create("example", credentials=credentials, dry_run=True)
receipt = await Publisher(database, adapter).publish(request)
```

## Safety boundary

The abstraction does not weaken platform controls. Approval gates, duplicate suppression, retries, scheduling, and live-mode opt-in remain outside adapters and continue to apply before official API calls are made. Browser automation, cookie reuse, scraping against platform rules, and fabricated engagement remain out of scope.
