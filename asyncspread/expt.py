class SpreadException(Exception):
    '''SpreadException class from pyspread code by Quinfeng.
    Note: This should be a smaller set of exception classes that map to
    categories of problems, instead of this enumerated list of errno strings.'''
    errors = { -1: 'ILLEGAL_SPREAD', # TODO: eliminate unnecessary errno values
        -2: 'COULD_NOT_CONNECT',
        -3: 'REJECT_QUOTA',
        -4: 'REJECT_NO_NAME', # doesn't happen: if you send empty string, server assigns your name
        -5: 'REJECT_ILLEGAL_NAME', # name too long, or bad chars
        -6: 'REJECT_NOT_UNIQUE', # name collides with another client!
        -7: 'REJECT_VERSION', # server thinks client is too old
        -8: 'CONNECTION_CLOSED',
        -9: 'REJECT_AUTH',
        -11: 'ILLEGAL_SESSION',
        -12: 'ILLEGAL_SERVICE',
        -13: 'ILLEGAL_MESSAGE',
        -14: 'ILLEGAL_GROUP',
        -15: 'BUFFER_TOO_SHORT',
        -16: 'GROUPS_TOO_SHORT',
        -17: 'MESSAGE_TOO_LONG',
        -18: 'NET_ERROR_ON_SESSION',
        'auth rejected': 'Authentication type was rejected by server.',
       'no connection': 'Not connected to spread server.' }

    def __init__(self, errno):
        Exception.__init__(self)
        self.errno = errno
        self.type = 'SpreadException' # TODO: should be cleaner
        self.msg = SpreadException.errors.get(errno, 'unrecognized error')

    def __str__(self):
        return ('%s(%d) # %s' % (self.type, self.errno, self.msg))

    def __repr__(self):
        return (self.__str__())

class SpreadAuthException(SpreadException):
    def __init__(self, errno):
        SpreadException.__init__(self, errno)
        self.type = 'SpreadAuthException' # TODO: clean up

