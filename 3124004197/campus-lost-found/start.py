import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dotenv import dotenv_values
from campus_app.version import backend_version

ROOT=Path(__file__).resolve().parent


def healthy(port, need_demo=False):
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/health',timeout=1) as response:
            data=json.load(response)
        settings = dotenv_values(ROOT/'.env')
        directory = Path(os.getenv('DATA_DIR') or settings.get('DATA_DIR') or str(ROOT/'data'))
        if not directory.is_absolute(): directory = ROOT/directory
        return (isinstance(data,dict) and data.get('application')=='campus-lost-found'
                and data.get('project_id')==hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
                and data.get('backend_version')==backend_version()
                and data.get('config_revision')==((ROOT/'.env').stat().st_mtime_ns if (ROOT/'.env').exists() else 0)
                and data.get('data_id')==hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:12]
                and (not need_demo or data.get('demo_enabled')))
    except (OSError,ValueError):return False


def available(port):
    with socket.socket() as sock:
        try:sock.bind(('0.0.0.0',port));return True
        except OSError:return False


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='首次启动加入明确标记的演示记录')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    child=None;port=None
    for candidate in range(8080,8091):
        if healthy(candidate,args.demo):port=candidate;break
        if available(candidate):port=candidate;break
    if port is None:
        print('8080～8090 端口均被占用，请关闭不需要的服务。');return 1
    try:
        if not healthy(port,args.demo):
            env=os.environ.copy()
            if args.demo:env['ENABLE_DEMO']='1'
            child=subprocess.Popen([sys.executable,'-m','uvicorn','campus_app.main:app','--app-dir',str(ROOT),'--host','0.0.0.0','--port',str(port)],cwd=ROOT,env=env)
            for _ in range(100):
                if healthy(port):break
                if child.poll() is not None:return child.returncode
                time.sleep(.2)
            else:print('服务启动超时，请检查依赖。');return 1
        url=f'http://127.0.0.1:{port}/'
        print('校园失物找回助手：'+url,flush=True)
        print('配置修改后需停止旧服务并重新启动。保持启动终端运行。',flush=True)
        if not args.no_browser:webbrowser.open_new_tab(url)
        return child.wait() if child else 0
    except KeyboardInterrupt:return 0
    finally:
        if child and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.terminate();child.wait()


if __name__=='__main__':sys.exit(main())
