"""Block network access for the whole test run.

`unittest discover` sorts module names, imports every test module, and only then runs
them, all in one process. This name sorts first, so importing it installs the block
before any test module is imported and every test in the run is covered.

`NetworkBlocked` inherits `BaseException`: code that catches `Exception` or
`RuntimeError` around a request must not be able to hide a test that reached out.
"""

import socket
import subprocess
import sys
import unittest
import urllib.request

GIT_NETWORK = ('fetch', 'push', 'ls-remote', 'clone', 'pull')


class NetworkBlocked(BaseException):
    """Raised instead of touching the network, and not catchable as an Exception."""


def _git_networking(argv):
    if not isinstance(argv, (list, tuple)):
        return False
    words = [str(item) for item in argv]
    return bool(words) and words[0] == 'git' and any(word in GIT_NETWORK for word in words[1:])


def _guard(command):
    def wrapper(*args, **kwargs):
        argv = args[0] if args else kwargs.get('args')
        if _git_networking(argv):
            raise NetworkBlocked('git network command: ' + ' '.join(str(item) for item in argv))
        return command(*args, **kwargs)
    wrapper.__name__ = getattr(command, '__name__', 'guarded')
    wrapper.__doc__ = getattr(command, '__doc__', None)
    return wrapper


def install():
    """Install the block once, so a repeated import cannot install it twice."""
    if getattr(socket.socket.connect, '__name__', '') == 'refused_connect':
        return
    def refused_connect(self, *args, **kwargs):
        raise NetworkBlocked('socket.socket.connect')

    def refused_connect_ex(self, *args, **kwargs):
        raise NetworkBlocked('socket.socket.connect_ex')

    def refused_urlopen(*args, **kwargs):
        raise NetworkBlocked('urllib.request.urlopen')

    refused_connect.__name__ = 'refused_connect'
    socket.socket.connect = refused_connect
    socket.socket.connect_ex = refused_connect_ex
    urllib.request.urlopen = refused_urlopen
    for name in ('run', 'Popen', 'check_output'):
        setattr(subprocess, name, _guard(getattr(subprocess, name)))


install()


class NetworkBlockTests(unittest.TestCase):
    def test_a_raw_socket_is_refused(self):
        with self.assertRaises(NetworkBlocked):
            socket.create_connection(('127.0.0.1', 9))

    def test_urlopen_is_refused(self):
        with self.assertRaises(NetworkBlocked):
            urllib.request.urlopen('https://api.cnb.cool/')

    def test_the_controller_api_cannot_reach_cnb(self):
        import control
        with self.assertRaises(NetworkBlocked) as caught:
            control.api('https://api.cnb.cool/x')
        self.assertNotIsInstance(caught.exception, RuntimeError)

    def test_the_socket_connect_is_the_block(self):
        self.assertEqual('refused_connect', socket.socket.connect.__name__)

    def test_git_network_commands_are_refused_and_local_ones_run(self):
        with self.assertRaises(NetworkBlocked):
            subprocess.run(['git', 'fetch', 'https://github.com/x/y.git'])
        self.assertEqual(0, subprocess.run(['git', '--version'], capture_output=True).returncode)

    def test_a_repeated_import_keeps_one_block(self):
        import importlib
        installed = socket.socket.connect, urllib.request.urlopen, subprocess.run
        importlib.reload(sys.modules[__name__])
        self.assertEqual(installed, (socket.socket.connect, urllib.request.urlopen, subprocess.run))


if __name__ == '__main__':
    unittest.main()
