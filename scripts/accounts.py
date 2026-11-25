"""Explicit local account maintenance. Passwords are prompted, never CLI arguments."""
import argparse
import getpass
import sys
from pathlib import Path
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api import main


def run():
    parser = argparse.ArgumentParser(description='RFQ账号维护；请以业务进程相同用户和RFQ_DB运行')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create-admin')
    create.add_argument('--username', required=True)
    create.add_argument('--name', required=True)
    reset = sub.add_parser('reset-password')
    reset.add_argument('--username', required=True)
    assign = sub.add_parser('assign-legacy')
    assign.add_argument('--username', required=True)
    assign.add_argument('--case', required=True, dest='case_id')
    args = parser.parse_args()
    print('目标数据库:', main.DB.resolve())
    if args.command == 'assign-legacy':
        with main.connection() as c:
            main.ACCOUNTS.schema(c)
            c.execute('BEGIN IMMEDIATE')
            user=c.execute('SELECT id FROM auth_users WHERE username=? COLLATE NOCASE', (args.username.strip(),)).fetchone()
            case=c.execute('SELECT id FROM cases WHERE id=?', (args.case_id,)).fetchone()
            owner=c.execute('SELECT visitor FROM case_owners WHERE case_id=?', (args.case_id,)).fetchone()
            if not user or not case: raise SystemExit('账号或工作单不存在，未修改')
            if owner and owner[0].startswith('user:'): raise SystemExit('工作单已属于账号，禁止覆盖归属')
            c.execute('INSERT OR REPLACE INTO case_owners VALUES(?,?)', (args.case_id,'user:'+user[0]))
            main.ACCOUNTS.audit(c,'local-console','legacy_assign',args.case_id+':'+user[0])
        print('已显式分配该历史工作单；原件及业务内容未修改')
        return
    password = getpass.getpass('新密码（15–128字符）: ')
    if password != getpass.getpass('再次输入: '):
        raise SystemExit('两次密码不一致，未保存')
    if args.command == 'create-admin':
        user = main.ACCOUNTS.create(args.username, args.name, password, role='admin', must_change=False)
        print('已创建管理员:', user['username'])
    else:
        from apps.api.accounts import password_hash
        hashed = password_hash(password)
        with main.connection() as c:
            main.ACCOUNTS.schema(c)
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT id FROM auth_users WHERE username=? COLLATE NOCASE', (args.username.strip(),)).fetchone()
            if not row: raise SystemExit('账号不存在，未修改')
            c.execute('UPDATE auth_users SET password=?,must_change=1 WHERE id=?', (hashed,row[0]))
            c.execute('DELETE FROM auth_sessions WHERE user_id=?', (row[0],))
            main.ACCOUNTS.audit(c, 'local-console', 'password_reset', row[0])
        print('已重置密码并撤销所有会话；下次登录须修改密码')


if __name__ == '__main__':
    try:
        run()
    except HTTPException as error:
        raise SystemExit(str(error.detail)) from None
