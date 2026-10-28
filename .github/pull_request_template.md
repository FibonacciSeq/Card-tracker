## What changed

<!-- Short description of the change. -->

## Why

<!-- The problem this solves, or a link to the issue. -->

## Checklist

- [ ] Legacy checks pass when touching root Python/Tkinter (`make check`, `make security`)
- [ ] Backend checks pass when touching `backend/` (Ruff, format, mypy, pytest)
- [ ] Admin checks pass when touching `admin/` (lint, typecheck, build, Playwright)
- [ ] Mobile checks pass when touching `mobile/` (lint, typecheck, web export, expo-doctor)
- [ ] Added or updated tests for the change
- [ ] Updated the relevant README/STATUS documentation if behaviour or setup changed
- [ ] No customer data, `cardtracker_shop.db`, `cardtracker_platform.db`, or `image_cache/` committed
