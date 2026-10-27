"""Choose a connection mode from the actual MCP schema, never guess an enum."""


def connection_args(schema):
    modes = schema.get('properties', {}).get('mode', {}).get('enum', [])
    for mode in ('auto', 'debug', 'pine'):
        if mode in modes:
            return {'mode': mode}
    raise ValueError('Unsupported PCSX2 connection schema')
