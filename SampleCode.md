# Echo Service #

```
#!/usr/bin/env python
import asyncspread

class EchoService(asyncspread.SpreadListener):
    def handle_data(conn, message):
        pass

spl = EchoService()
spconn = asyncspread.AsyncSpread(name='server', host='127.0.0.1', port=4803, listener=spl)

# Work in Progress!

```

This is a client application that joins a channel named "echo" and receives messages sent to that channel, and sends a unicast echo response back to the individual sender using their private name.

# Command Service #

```
# TO DO
```