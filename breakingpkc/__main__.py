# Keep module execution as a thin adapter over the same CLI used by developer tests.
from .cli import main

raise SystemExit(main())
