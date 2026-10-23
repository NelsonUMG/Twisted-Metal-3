import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from release_updater import check_update, download_installer, launch_installer
from lobby_client import Lobby

class Response(BytesIO):
    def geturl(self): return 'https://release-assets.githubusercontent.com/file'

class UpdateFlowTests(unittest.TestCase):
    def update(self, data):
        return dict(url='https://github.com/test',size=len(data),sha256=hashlib.sha256(data).hexdigest())

    def test_progress_reaches_size(self):
        data=b'x'*600000; events=[]
        with tempfile.TemporaryDirectory() as folder, patch('release_updater.urlopen',return_value=Response(data)):
            path=download_installer(self.update(data),folder,lambda *args: events.append(args))
            self.assertEqual(path.read_bytes(),data)
            self.assertEqual(events[0],(0,len(data)))
            self.assertEqual(events[-1],(len(data),len(data)))
            self.assertEqual(sorted(events),events)

    def test_cancel_mid_download_removes_partial(self):
        data=b'x'*600000; cancel=threading.Event()
        with tempfile.TemporaryDirectory() as folder, patch('release_updater.urlopen',return_value=Response(data)):
            with self.assertRaises(InterruptedError):
                download_installer(self.update(data),folder,lambda done,total: cancel.set() if done else None,cancel)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_network_failure_preserves_existing_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'TM3Online-Setup.exe'; path.write_bytes(b'old')
            with patch('release_updater.urlopen',side_effect=OSError('offline')):
                with self.assertRaises(OSError): download_installer(self.update(b'new'),folder)
            self.assertEqual(path.read_bytes(),b'old')

    def test_missing_release_is_quiet(self):
        with patch('release_updater.urlopen',side_effect=HTTPError('url',404,'missing',{},None)):
            self.assertIsNone(check_update('0.2.0'))

    def test_auth_failure_is_not_latest(self):
        with patch('release_updater.urlopen',side_effect=HTTPError('url',403,'denied',{},None)):
            with self.assertRaises(HTTPError): check_update('0.2.0')

    def test_changed_installer_cannot_launch(self):
        with tempfile.TemporaryDirectory() as folder, patch('release_updater.subprocess.Popen') as launch:
            path=Path(folder)/'setup.exe';path.write_bytes(b'bad')
            with self.assertRaises(ValueError): launch_installer(path,folder,self.update(b'good'))
            launch.assert_not_called()

    def test_restart_targets_install_folder_and_waits_for_parent(self):
        with tempfile.TemporaryDirectory() as folder, patch('release_updater.subprocess.Popen') as launch:
            path=Path(folder)/'setup.exe';path.write_bytes(b'good')
            launch_installer(path,folder,self.update(b'good'))
            args=launch.call_args.args[0]
            self.assertIn('/TM3RESTART=1',args)
            self.assertTrue(any(a.startswith('/WAITPID=') for a in args))
            self.assertIn('/DIR='+str(Path(folder).resolve()),args)
            self.assertFalse(launch.call_args.kwargs['shell'])

    def test_check_only_once_per_launch(self):
        class InlineThread:
            def __init__(self,target,**kwargs): self.target=target
            def start(self): pass
        lobby=Lobby.__new__(Lobby)
        with patch('lobby_client.threading.Thread',side_effect=InlineThread) as worker:
            lobby.check_release_update(automatic=True)
            lobby.check_release_update(automatic=True)
            self.assertEqual(worker.call_count,1)

if __name__=='__main__': unittest.main()

class UpdateWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from types import SimpleNamespace
        import queue
        self.root=tk.Tk();self.root.withdraw()
        self.folder=tempfile.TemporaryDirectory()
        self.owner=SimpleNamespace(root=self.root,events=queue.Queue(),update_cache=Path(self.folder.name),install_root=Path(self.folder.name),room=None,process=None,local_process=None,close=unittest.mock.Mock())
    def tearDown(self):
        self.root.destroy();self.folder.cleanup()
    def dialog(self):
        from update_window import UpdateWindow
        with patch('update_window.threading.Thread'):
            return UpdateWindow(self.owner,dict(version='v0.3.0',size=100,sha256='a'*64))
    def test_progress_and_verified_ready(self):
        window=self.dialog();window.progress(40,100)
        self.assertEqual(window.bar['value'],40)
        self.assertIn('disabled',window.restart.state())
        window.ready('verified.exe')
        self.assertNotIn('disabled',window.restart.state())
        with patch('release_updater.launch_installer') as launch:
            window.apply();launch.assert_called_once_with('verified.exe',self.owner.install_root,window.update)
            self.owner.close.assert_called_once()
    def test_launch_failure_keeps_application_open(self):
        window=self.dialog();window.ready('bad.exe')
        with patch('release_updater.launch_installer',side_effect=OSError('locked')):
            window.apply()
        self.owner.close.assert_not_called()
        self.assertTrue(window.window.winfo_exists())
    def test_cancel_closes_dialog_and_sets_signal(self):
        window=self.dialog();window.hide()
        self.assertTrue(window.cancelled.is_set())
        window.progress(10,100);window.failed('offline');window.ready('ignored')
        self.owner.close.assert_not_called()
