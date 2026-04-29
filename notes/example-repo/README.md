# example-repo

This is a placeholder repo subdirectory showing the per-repo notes layout.

When you set up `notes_root` in your config and add a repo block like:

```yaml
repos:
  myproject:
    github: your-org/myproject
    local: /path/to/local/checkout
```

…create `<notes_root>/myproject/` to mirror this pattern. Active tracks at the
top level, archived tracks under `archive/{shipped,abandoned}/`.

You can delete this `example-repo/` directory once you've created your own.
