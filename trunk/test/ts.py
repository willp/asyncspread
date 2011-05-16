#!/usr/bin/python -u
import time, sys, logging
sys.path.append('.')
from asyncspread.connection import AsyncSpread, AsyncSpreadThreaded
from asyncspread.listeners import SpreadListener, SpreadPingListener, CallbackListener, GroupCallback
from asyncspread.services import ServiceTypes

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

setup_logging(logging.DEBUG)

class MyListener(SpreadPingListener):
    def handle_ping(self, success, elapsed):
        print '***808 PONG:  Success:', success, ' Elapsed:', elapsed

    def handle_data(self, conn, mesg):
        print '*** Got message:', mesg.data

def ping_cb(success, elapsed):
    print '*** PONG:  Success:', success, ' Elapsed:', elapsed

def conn_cb(listener, conn):
    print 'Got authenticated.'
    conn.unicast('hb', 'I just joined! Hello!', 0)
def drop_cb(listener, conn):
    print 'Client > DROPPED < CB:  conn:', conn
    print 'GOING TO RESTART CONNECT. Timeout 10'
    #conn.do_restart.set()
    conn.wait_for_connection(5)
    conn.start_connect(5)
    print 'done with start_connect...'
#    raise ValueError('This simulates a client code error in the callback.')
def err_cb(listener, conn, exc):
    print 'Client > ERROR <  CB: conn:', conn, 'Exception:', exc
#    raise ValueError('This simulates a client code error in the callback.')
def data_cb(conn, message):
    print 'Client data CB, mesg len:', len(message.data), 'sender:', message.sender, 'groups:', message.groups
def start_end_cb(conn, group, membership):
    print 'Client start/end CB:  conn:', conn, 'group:', group, 'membership:', membership
def join_leave_cb(conn, group, member, cause):
    print 'Client join/leave CB:  conn:', conn, 'group:', group, 'member:', member, 'cause:', cause
def split_cb(conn, group, changes, old_membership, new_membership):
    print 'Client Network Split CB: conn:', conn, 'group:', group, 'Number changes:', changes, 'Old Members:', old_membership, 'New members:', new_membership

mylistener = MyListener()
mylistener2 = CallbackListener(cb_conn=conn_cb, cb_error=err_cb, cb_dropped=drop_cb)
mylistener2.set_group_cb('gr1', GroupCallback(cb_data=data_cb,
                                    cb_start=start_end_cb, cb_end=start_end_cb,
                                    cb_join=join_leave_cb, cb_leave=join_leave_cb,
                                    cb_network=split_cb))
myname = 'ts.py-%03d' % (int(time.time()*10) % 1000)
#myname = 'rb01'
#print 'My name is: "%s"' % myname
host = 'localhost'
port = 24999
if len(sys.argv) > 1:
    host = sys.argv[1]
if len(sys.argv) > 2:
    port = int(sys.argv[2])
sp1 = AsyncSpread(myname, host, port, listener=mylistener2, start_connect=True)
print 'Connecting to %s:%d' % (host, port)
sp1.set_level(ServiceTypes.UNRELIABLE_MESS)
ret = sp1.connected
print 'Connected?', ret
if ret:
    print 'my private session name is:', sp1.session_name
for g in ('gr1', 'group2', 'gr2', 'gr5', 'AZ'):
    sp1.join(g)

for i in xrange(1, 10):
    if sp1.dead:
        break
    groups = ['gr1']
    if i % 5 == 0:
        groups.append('gr3')
        groups.append('gr5')
    if i % 6 == 0:
        sp1.multicast(groups, '', ((i*101) % 65535), self_discard=False)
    else:
        sp1.multicast(groups, 'Test message number %d' % (i), ((i*100) % 0xffff), self_discard=False)
    if i % 10 == 5:
        sp1.leave('gr2')
        sp1.join('gr1')
        sp1.multicast(['gr1'], 'Just joined! i=%d, and self-discard set to False' % (i), 0xff00, self_discard=False)
    if i % 10 == 2:
        sp1.leave('gr1')
        sp1.join('gr2')
        sp1.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff, self_discard=False)
    sp1.multicast(['gr1'], "A" * 90, 0, self_discard=False) # send big message
    time.sleep(0.5)
print 'Entering big long lasting sleep (30) ...'
time.sleep(30)
print 'Done with big loop..'
sp1.leave('gr18')
print 'About to disconnect...'
sp1.disconnect(shutdown=True)
print 'about to exit...'
time.sleep(2)
print 'now calling shutdown..'
#sp1.do_shutdown()
#sp2.do_shutdown()
print 'ran shutdown methods... hopefully will exit now'
print 'Object:', sp1
sys.exit(0)
