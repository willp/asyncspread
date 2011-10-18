#!/usr/bin/env python

import logging, os, sys, time, traceback
sys.path.extend(['.', '..'])

from asyncspread.connection import AsyncSpread
from asyncspread.services import ServiceTypes
from asyncspread.listeners import CallbackListener, GroupCallback
from asyncspread.listeners import SpreadPingListener

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)


(host, port) = ('localhost', 4803)
if len(sys.argv) > 1: host = sys.argv[1]
if len(sys.argv) > 2: port = int(sys.argv[2])

setup_logging()

myname = 'cli-%03d' % (int(time.time() * 100) % 1000)
print ('I am %s' % myname)

def got_conn(listener, conn):
    print ('Got connected: %s' % conn)

def got_dropped(listener, conn):
    print ('Lost connection to spread server on:%s  Reconnecting with start_connect()' % conn.name)
    conn.start_connect()

def got_error(listener, conn, exc):
    print ('Got exception/error: %s' % str(exc))
    if 'Connection refused' in exc:
        print ('Connection refused by server... Sleeping 1 seconds...')
        time.sleep(1)

def got_mesg(listener, conn, mesg):
    print ('%s>> Got message, type=%4d, sender="%s", message: %s' % (conn.name, mesg.mesg_type, mesg.sender, mesg.data))

my_listener = CallbackListener(cb_conn=got_conn, cb_dropped=got_dropped, cb_error=got_error, cb_data=got_mesg)
hb_client = AsyncSpread(myname, host, port, listener=my_listener, start_connect=True)
hb_client.set_level(ServiceTypes.AGREED_MESS)

for loop in xrange(10000):
    print ('%s: client top of loop %d' % (myname, loop))
    hb_client.run(count=10, timeout=0.1)  # spend up to 1 sec doing IO
    if loop % 3 == 0:
        # every 3 seconds, send a message to heartbeat channel
        try:
            print ('Sending heartbeat message to server')
            hb_client.unicast(':HB', 'heartbeat ping from client PID %d' % (os.getpid()), loop // 10)
        except:
            print ('cannot send, not connected?')
            (exc_type, exc_val, tback) = sys.exc_info()
            print ('Exception: %s / %s' % (exc_type, exc_val))
            traceback.print_tb(tback)
    if not hb_client.is_connected():
        print ('Not connected to server. Reconnecting...')
        hb_client.disconnect()
        hb_client.start_connect()
