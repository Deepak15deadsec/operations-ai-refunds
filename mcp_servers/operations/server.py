"""Entry point kept at the path named in the spec. The implementation lives in the
`operations_mcp` package so it can be installed and tested as a workspace member."""

from operations_mcp.server import main

if __name__ == "__main__":
    main()
