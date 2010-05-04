#!/usr/bin/python2.6
import time, sys, logging
sys.path.append('.')
import asyncspread

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
logger.addHandler(ch)

def ping_response(success, elapsed):
    print 'Client PING callback: Success=', success
    print '   Elapsed time: %.8f' % (elapsed)


def mesg_cb(mesg):
    print '*** Got message:', mesg.data

listener = asyncspread.SpreadPingListener()

myname = 'tra-%06d' % (int(time.time()*100) % 1000)
print 'I am', myname
#myname = ''
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999, listener=listener)
sp.start_connect()
sp.join(['gr1', 'gr2', 'abc123', 'def'])
while sp.connected:
    print 'client top of loop'
    listener.ping(sp, ping_response)
    sp.loop(150)

#sp.connect()
#sp.join(['gr1', 'gr2', 'gr3', 'group1', 'group2', 'group3'])
#sp.multicast([sp.private_name], 'Message to myself %f' % (time.time()), 0)
#i = 0
#while True:
#    i += 1
#    print '      ',sp.receive()

