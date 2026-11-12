#!/usr/bin/env python3
# Secret scan over every added line in git history. Prints redacted hits only.
# Usage: python3 tools/secret_scan.py [repo_path]   (run before making a repo public)
import re,subprocess,sys
PAT={
 'aws_key':r'AKIA[0-9A-Z]{16}','gh_token':r'gh[pousr]_[A-Za-z0-9]{36,}','gh_pat':r'github_pat_[A-Za-z0-9_]{50,}',
 'anthropic':r'sk-ant-[A-Za-z0-9_-]{20,}','openai':r'sk-(proj-)?[A-Za-z0-9]{20,}','google_api':r'AIza[0-9A-Za-z_-]{35}',
 'google_oauth_secret':r'GOCSPX-[A-Za-z0-9_-]{20,}','slack':r'xox[baprs]-[A-Za-z0-9-]{10,}','stripe':r'[sr]k_(live|test)_[A-Za-z0-9]{20,}',
 'private_key':r'-----BEGIN [A-Z ]*PRIVATE KEY-----','jwt':r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
 'conn_string':r'(postgres|postgresql|mysql|mongodb(\+srv)?|redis|amqp)://[^\s:/]+:[^\s@/]+@','netlify':r'nfp_[A-Za-z0-9]{30,}',
 'firecrawl':r'fc-[a-f0-9]{32}','gmail_app_pw':r'(?i)(app[_ ]?pass(word)?|smtp_pass|imap_pass)\W{0,5}[a-z]{4} ?[a-z]{4} ?[a-z]{4} ?[a-z]{4}',
 'generic_assign':r'(?i)\b(api[_-]?key|secret|token|passwd|password|client[_-]?secret|access[_-]?key|auth)\b["\']?\s*[:=]\s*["\'][^"\'\s]{12,}["\']',
 'b64_blob_env':r'MAIL_ACCOUNTS_B64\s*=\s*\S{20,}','bearer':r'(?i)bearer\s+[A-Za-z0-9._-]{30,}',
}
repo=sys.argv[1] if len(sys.argv)>1 else "."
out=subprocess.run(['git','-C',repo,'log','--all','-p','--no-color','--format=COMMIT %h'],capture_output=True,text=True,errors='replace').stdout
commit=file=None;hits={}
for line in out.splitlines():
    if line.startswith('COMMIT '):commit=line[7:];continue
    if line.startswith('+++ b/'):file=line[6:];continue
    if not line.startswith('+') or line.startswith('+++'):continue
    for k,p in PAT.items():
        for m in re.finditer(p,line):
            s=m.group(0);red=s[:6]+'…'+str(len(s))
            hits.setdefault((k,file,red),commit)

for (k,f,r),c in sorted(hits.items()):print(f'{k:20} {c} {f} {r}')
print('TOTAL',len(hits))
