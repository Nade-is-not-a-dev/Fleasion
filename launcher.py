"""PyInstaller entry point."""

import sys


if '--linux-proxy-helper' in sys.argv[1:]:
    sys.argv.remove('--linux-proxy-helper')
    from fleasion import linux_proxy_helper_daemon

    linux_proxy_helper_daemon.main()
else:
    from fleasion import main

    main()
