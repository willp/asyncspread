#!/usr/bin/env python

import time, sys, logging, traceback, binascii
sys.path.extend(['.', '..'])

from asyncspread.connection import AsyncSpread
from asyncspread.listeners import SpreadListener

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)


class HeartbeatServer(SpreadListener):
    def __init__(self):
        SpreadListener.__init__(self)
        self.hb_count = self.hb_sent = 0
        self.name = 'srv-%03d' % (int(time.time() * 100) % 1000)
        print ('I am: %s' % self.name)

    def handle_connected(self, conn):
        print ('Got connected: %s\nJoining the :HB channel...' % (conn))
        conn.join(':HB')

    def handle_dropped(self, conn):
        print ('Lost connection to spread server on: %s - Reconnecting with start_connect()' % (conn.name))
        conn.start_connect()

    def handle_error(self, conn, exc):
        print ('Got exception/error: %s' % str(exc))
        if 'Connection refused' in exc:
            print ('Connection refused by server... Sleeping 1 second before reconnect')
            time.sleep(1)

    def compute_responder(self, sender, conn):
        '''
        Method to compute a subset of responders based on the current group membership and
        sender's name, to calculate a single responder based on hashing the sender's name
        with the current count of the number of servers listening, taking it modulus the number
        of servers and comparing it to my position in the list of servers on the channel.  Only one
        server will respond with this math.
        
        Computing the position could be cached and updated whenever there are membership
        changes, but for now it's done every time because this is sample code.
        '''
        members = list(self.get_group_members(':HB'))
        num_servers = len(members)
        members.sort() # we need a stable ordering
        position = members.index(conn.session_name)
        sender = sender.encode('utf-8')
        hash_mod = binascii.crc32(sender) % num_servers
        ok = bool(hash_mod == position)
        if ok:
            print ('I REPLY TO %r    (%d/%d)' % (sender, hash_mod, position))
        else:
            print ('I DO >NOT< REPLY TO %r  (%d/%d)' % (sender, hash_mod, position))
        return ok

    def handle_group_start(self, conn, group, membership):
        print ('I JOINed the group (%s).  Current # of HB servers: %d' % (group, len(membership)))
        print ('Current members: %s' % membership)

    def handle_group_join(self, conn, group, member, cause):
        print ('Another HB server JOINed group %s: "%s" joined. Reason: %s' % (group, member, cause))
        print ('Total HB servers listening: %d' % len(self.get_group_members(group)))

    def handle_group_leave(self, conn, group, member, cause):
        print ('A HB server LEFT: "%s" left group %s. Reason: %s' % (member, group, cause))
        print ('Total HB servers listening: %d' % len(self.get_group_members(group)))

    def handle_data(self, conn, message):
        self.hb_count += 1
        sender = str(message.sender)
        data = message.data
        mtype = message.mesg_type
        do_reply = self.compute_responder(sender, conn)
        print ('%s>> HB received: type=%d, sender="%s", message: %s' % (conn.name, mtype, sender, data))
        if do_reply:
            self.send_reply(conn, sender, mtype)

    def send_reply(self, conn, recipient, mtype):
            # send a response back
            self.hb_sent += 1
            print ('%s>> sending reply!' % (conn.name))
            reply = 'HB Reply:: %d received, %d sent messages' % (self.hb_count, self.hb_sent)
            try:
                conn.unicast(recipient, reply, mtype + 1)
            except:
                print ('Lost connection when attempting to reply.')
                (exc_type, exc_val, tback) = sys.exc_info()
                print ('Exception: %s / %s' % (exc_type, exc_val))
                traceback.print_tb(tback)

setup_logging()
hb_listener = HeartbeatServer()

(host, port) = ('localhost', 4803)
if len(sys.argv) > 1: host = sys.argv[1]
if len(sys.argv) > 2: port = int(sys.argv[2])

hb_srv = AsyncSpread(hb_listener.name, host, port, listener=hb_listener, start_connect=True)

print ('I am hb srv: %s' % hb_srv)

for loop in xrange(10000):
    hb_srv.run(10, timeout=0.1)
