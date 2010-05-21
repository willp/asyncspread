#!/usr/bin/python
import time, sys, logging, threading, random
sys.path.append('.')
import asyncspread

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    #ch.setLevel(level)
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

setup_logging(logging.DEBUG)

class MyListener(asyncspread.SpreadPingListener):
    def handle_ping(self, success, elapsed):
        print '***808 PONG:  Success:', success, ' Elapsed:', elapsed

    def handle_data(self, conn, mesg):
        print '*** Got message:', mesg.data

def ping_cb(success, elapsed):
    print '*** PONG:  Success:', success, ' Elapsed:', elapsed

def auth_cb(listener, conn):
    print 'Got authenticated.'
def drop_cb(listener, conn):
    print 'Client > DROPPED < CB:  conn:', conn
    print 'Setting reconnect flag'
    conn.do_reconnect = True
    #ret = conn.start_connect()
    #conn.start_io_thread()
def err_cb(listener, conn, exc):
    print 'Client > ERROR <  CB: conn:', conn, 'Exception:', exc
def data_cb(conn, message):
    print 'Client data CB:  conn:', conn, 'message length:', len(message.data)
def start_end_cb(conn, group, membership):
    print 'Client start/end CB:  conn:', conn, 'group:', group, 'membership:', membership
def join_leave_cb(conn, group, member, cause):
    print 'Client start/end CB:  conn:', conn, 'group:', group, 'member:', member, 'cause:', cause
def split_cb(conn, group, changes, old_membership, new_membership):
    print 'Client Network Split CB: conn:', conn, 'group:', group, 'Number changes:', changes, 'Old Members:', old_membership, 'New members:', new_membership

listener = MyListener() # asyncspread.SpreadListener()
listener2 = asyncspread.CallbackListener(cb_auth=auth_cb, cb_error=err_cb, cb_dropped=drop_cb)
listener2.set_group_cb('gr1', asyncspread.GroupCallback(cb_data=data_cb,
                                    cb_start=start_end_cb, cb_end=start_end_cb,
                                    cb_join=join_leave_cb, cb_leave=join_leave_cb,
                                    cb_network=split_cb))
myname = '\'%03d' % (int(time.time()*10) % 1000)
myname = 'rb01'
#print 'My name is: "%s"' % myname
print 'Connecting to %s' % (sys.argv[1])
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999, listener=listener2)
sp.set_level(asyncspread.ServiceTypes.UNRELIABLE_MESS)
ret = sp.start_connect()

print 'Connected?', ret
if ret:
    print 'my private name is:',sp.private_name
    sp.start_io_thread(forever=True)
for g in ('gr1', 'group2', 'gr2', 'gr5'):
    sp.join(g)

#sp.loop(1)
for i in xrange(1, 16):
    if sp.dead:
        break
    groups = ['gr1']
    if i % 5 == 0:
        groups.append('gr3')
        groups.append('gr5')
    if i % 6 == 0:
        sp.multicast(groups, '', ((i*101) % 65535), self_discard=False)
    else:
        sp.multicast(groups, 'Test message number %d' % (i), ((i*100) % 0xffff), self_discard=False)
#    if i % 10 == 9:
#        listener.ping(sp, ping_cb, 5)
#    print 'sent off my messages for iteration %d' % (i)
    if i % 10 == 5:
        sp.leave('gr2')
        sp.join('gr1')
        sp.multicast(['gr1'], 'Just joined! i=%d, and self-discard set to False' % (i), 0xff00, self_discard=False)
    if i % 10 == 2:
        sp.leave('gr1')
        sp.join('gr2')
        sp.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff, self_discard=False)
    sp.multicast(['gr1'], "A" * 900, 0, self_discard=False) # send big message
    #sp.loop(1)
    time.sleep(1)
    print
print 'Entering big long lasting loop...'
time.sleep(20)
#sp.loop(60000)
print 'Done with big loop..'
sp.leave('gr18')
sp.disconnect()
#sp.loop(10)
print 'about to exit...'
time.sleep(2)
sys.exit(0)
