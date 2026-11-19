#!/usr/bin/env python3
"""Install a per-user launchd dispatcher for authorized Content Factory work."""
import argparse,os,plistlib,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--remote-config',type=Path,default=Path.home()/'.config/content-factory/remote.json')
p.add_argument('--start',action='store_true');args=p.parse_args()
root=Path(__file__).resolve().parents[1]
if sys.platform!='darwin':raise SystemExit('Use systemd with scripts/factory_scheduler.py on non-macOS hosts')
if not args.remote_config.is_file():raise SystemExit('Remote config must already exist')
label='ai.frozo.content-factory.scheduler'
logs=root/'.runtime/logs';logs.mkdir(parents=True,exist_ok=True)
path=Path.home()/'Library/LaunchAgents'/f'{label}.plist';path.parent.mkdir(parents=True,exist_ok=True)
data={'Label':label,'ProgramArguments':[str(root/'.venv/bin/python'),str(root/'scripts/factory_scheduler.py'),'--remote-config',str(args.remote_config.resolve())],
      'WorkingDirectory':str(root),'EnvironmentVariables':{'PATH':str(Path.home()/'.local/bin')+':/opt/homebrew/bin:/usr/bin:/bin'},
      'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':str(logs/'scheduler.log'),'StandardErrorPath':str(logs/'scheduler-error.log')}
path.write_bytes(plistlib.dumps(data));path.chmod(0o600)
if args.start:
 domain=f'gui/{os.getuid()}'
 if subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True).returncode==0:
  subprocess.run(['launchctl','bootout',domain+'/'+label],check=True)
 subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
print(path)
