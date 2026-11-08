"""Consistent SQLite and referenced-photo backup. Never packages .env or existing backups."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent.parent


def backup(directory, output):
    directory=Path(directory).resolve();output=Path(output).resolve()
    database=directory/'campus.db'
    if not database.is_file():raise ValueError('数据目录中不存在 campus.db')
    if output.exists():raise ValueError('备份文件已存在，不会覆盖')
    output.parent.mkdir(parents=True,exist_ok=True)
    created=False
    try:
        with tempfile.TemporaryDirectory(prefix='campus-backup-') as temporary:
            snapshot=Path(temporary)/'campus.db'
            with sqlite3.connect(database,timeout=10) as lock:
                lock.execute('BEGIN IMMEDIATE')
                # WAL allows a separate reader while the reservation prevents database/image replacement.
                with sqlite3.connect(database) as source,sqlite3.connect(snapshot) as target:
                    source.backup(target)
                    rows=source.execute('SELECT DISTINCT photo_url FROM items WHERE deleted=0 AND photo_url IS NOT NULL').fetchall()
                photos=[]
                uploads=directory/'uploads'
                for (url,) in rows:
                    path=uploads/Path(url).name
                    if not path.is_file() or path.is_symlink() or path.resolve().parent!=uploads.resolve():
                        raise ValueError('存在缺失或不安全的照片路径，备份已停止')
                    photos.append(path)
                with output.open('xb') as file:
                    created=True
                    os.chmod(output,0o600)
                    with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.write(snapshot,'campus.db')
                        for photo in photos:archive.write(photo,'uploads/'+photo.name)
                lock.rollback()
    except BaseException:
        if created:output.unlink(missing_ok=True)
        raise
    return output


def main():
    settings=dotenv_values(ROOT/'.env')
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=Path(os.getenv('DATA_DIR') or settings.get('DATA_DIR') or str(ROOT/'data')))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    directory=args.data_dir if args.data_dir.is_absolute() else ROOT/args.data_dir
    filename='campus-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip'
    output=args.output or directory/'backups'/filename
    try:result=backup(directory,output)
    except (ValueError,OSError,sqlite3.Error) as exc:
        print('备份失败：'+str(exc));return 1
    print('备份已生成：'+str(result));return 0


if __name__=='__main__':raise SystemExit(main())
