![http://nuclei.com/asyncspread/AsyncSpread_sm3.png](http://nuclei.com/asyncspread/AsyncSpread_sm3.png)

Asynchronous client API for Spread message brokers, implemented in python.  This is a pure-python implementation of a high-performance non-blocking and asynchronous API to group communications on the Spread message bus.

## Example Code ##

See the [Examples](Examples.md) page for instructions on how to run the included "heartbeat service" client and server code with spread.

## API Docs ##

See the [API Documentation](http://nuclei.com/asyncspread/apidocs/) for the client API.

## Updates ##
See the [ProjectUpdates](ProjectUpdates.md) page!

This project uses [Spread Concepts](http://spread.org/) messaging protocols, and is a re-write of another Google Code project, [py-spread](http://code.google.com/p/py-spread/) using the Python standard library asyncore and asynchat classes.

# Goals #
  * Pure python implementation
  * Requires only standard libraries
  * Re-uses existing asyncore and asynchat as much as possible
  * Works on python >= 2.4
  * Python 3 support "soon"
  * Support group membership and presence status
  * Handle network faults gracefully and transparently
  * Work in multi-threaded applications if so desired


### Thanks ###
Thanks to [Qingfeng](http://code.google.com/u/paradise.qingfeng/) for his implementation of py-spread which helped start this project with code for the protocol encoding and decoding.  I have started with this codebase and am grateful for Qingfeng's contribution to open source and to the Spread group communications codebase.