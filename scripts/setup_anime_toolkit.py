"""Install the pinned anime runtime and local dependencies; never generates paid media."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.anime_toolkit import REVISION, UPSTREAM, environment, ruby, runtime


def main():
    exe=ruby()
    if not exe: raise SystemExit('Install Ruby 3.2+ or configure ANIME_RUBY first.')
    checkout=runtime().parents[2]
    if checkout.exists():
        if not (checkout/'.git').is_dir():
            raise SystemExit('Existing checkout has no Git revision metadata; inspect it before replacing it.')
        actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
        if actual!=REVISION: raise SystemExit('Existing checkout differs from pinned revision; use a fresh ANIME_TOOLKIT_HOME.')
    else:
        checkout.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','clone','--no-checkout',UPSTREAM+'.git',str(checkout)],check=True)
        subprocess.run(['git','-C',str(checkout),'checkout','--detach',REVISION],check=True)
    env=environment()
    # All package installation is explicit setup, never hidden in an MCP call.
    subprocess.run([exe,'-S','gem','install','bundler','-v','4.0.20','--no-document'],env=env,check=True)
    subprocess.run([exe,'-S','bundle','install'],cwd=runtime(),env=env,check=True)
    subprocess.run(['npm','ci','--ignore-scripts'],cwd=runtime(),env=env,check=True)
    subprocess.run([sys.executable,'-m','pip','install','-r',str(runtime()/'requirements.txt')],check=True)
    print('Anime toolkit installed at pinned revision '+REVISION+'. No media was generated.')


if __name__=='__main__': main()
