"""
V1.1 Enterprise 未接收自動催辦 worker
建議每 1 分鐘執行一次：
    python worker.py

需要環境變數：
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
SMTP_FROM
SMTP_USE_SSL=true/false
LINE_CHANNEL_ACCESS_TOKEN

注意：SUPABASE_SERVICE_ROLE_KEY 只能放在可信任的後端/排程器，絕不可放前端或 GitHub 公開倉庫。
"""
import os
import ssl
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests
from supabase import create_client

SUPABASE_URL=os.environ["SUPABASE_URL"]
SERVICE_KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb=create_client(SUPABASE_URL,SERVICE_KEY)

def age_minutes(iso):
    dt=datetime.fromisoformat(iso.replace("Z","+00:00"))
    return int((datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()//60)

def send_email(to_email, subject, body):
    if not to_email:
        return "略過(無Email)"
    host=os.getenv("SMTP_HOST","")
    if not host:
        return "略過(未設定SMTP)"
    port=int(os.getenv("SMTP_PORT","587"))
    user=os.getenv("SMTP_USER","")
    password=os.getenv("SMTP_PASSWORD","")
    sender=os.getenv("SMTP_FROM",user)
    use_ssl=os.getenv("SMTP_USE_SSL","false").lower()=="true"
    msg=EmailMessage()
    msg["Subject"]=subject
    msg["From"]=sender
    msg["To"]=to_email
    msg.set_content(body)
    context=ssl.create_default_context()
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host,port,context=context,timeout=20) as s:
                if user: s.login(user,password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host,port,timeout=20) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                if user: s.login(user,password)
                s.send_message(msg)
        return "成功"
    except Exception as e:
        return f"失敗:{type(e).__name__}:{e}"[:300]

def send_line(line_user_id, body):
    if not line_user_id:
        return "略過(無LINE ID)"
    token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN","")
    if not token:
        return "略過(未設定LINE Token)"
    try:
        r=requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"to":line_user_id,"messages":[{"type":"text","text":body[:4900]}]},
            timeout=20,
        )
        return "成功" if 200 <= r.status_code < 300 else f"失敗:HTTP {r.status_code}:{r.text[:160]}"
    except Exception as e:
        return f"失敗:{type(e).__name__}:{e}"[:300]

def build_message(i, level, threshold, target_label):
    return (
        f"【生產異常第{level}次催辦】\n"
        f"異常編號：{i['abnormal_no']}\n"
        f"異常類型：{i['abnormal_type']}\n"
        f"工單單號：{i.get('work_order','')}\n"
        f"生產機種：{i.get('model','')}\n"
        f"工單數量：{i.get('work_qty',0)}\n"
        f"不良數量：{i.get('defect_qty',0)}\n"
        f"物料料號：{i.get('material_no','')}\n"
        f"製程別：{i.get('process_name','')}\n"
        f"通報人員：{i.get('reporter_name','')}\n"
        f"通報時間：{i.get('report_time','')}\n"
        f"異常描述：{i.get('abnormal_desc','')}\n\n"
        f"此案件已超過 {threshold} 分鐘尚未接收。\n"
        f"通知層級：{target_label}"
    )

def main():
    rules=sb.table("notification_rules").select("*").eq("enabled",True).order("level").execute().data or []
    incidents=(sb.table("incidents").select("*")
               .eq("process_progress","待受理").is_("receive_time","null")
               .execute().data or [])
    sent=0
    for i in incidents:
        age=age_minutes(i["report_time"])
        for rule in rules:
            lv=int(rule["level"]); threshold=int(rule["threshold_minutes"])
            if age < threshold:
                continue
            exists=(sb.table("notification_logs").select("id")
                    .eq("incident_id",i["id"]).eq("level",lv).limit(1).execute().data or [])
            if exists:
                continue
            members=(sb.table("notification_members").select("user_id")
                     .eq("level",lv).execute().data or [])
            ids=[x["user_id"] for x in members]
            profiles=[]
            for uid in ids:
                p=(sb.table("profiles").select("display_name,email,line_user_id,active")
                   .eq("id",uid).eq("active",True).limit(1).execute().data or [])
                profiles += p
            body=build_message(i,lv,threshold,rule["target_label"])
            subject=f"[生產異常第{lv}次催辦] {i['abnormal_no']} 未接收"
            results_email=[]; results_line=[]; names=[]
            for p in profiles:
                names.append(p["display_name"])
                results_email.append(f"{p['display_name']}:{send_email(p.get('email',''),subject,body)}")
                results_line.append(f"{p['display_name']}:{send_line(p.get('line_user_id',''),body)}")
            if not profiles:
                results_email=["無設定通知人員"]; results_line=["無設定通知人員"]
            try:
                sb.table("notification_logs").insert({
                    "incident_id":i["id"],"abnormal_no":i["abnormal_no"],"level":lv,
                    "notify_target":"、".join(names) or rule["target_label"],
                    "email_result":" | ".join(results_email),
                    "line_result":" | ".join(results_line),
                    "note":f"未接收超過 {threshold} 分鐘"
                }).execute()
                sent += 1
            except Exception as e:
                # UNIQUE(incident_id, level) 可避免多個 worker 重複建立同級通知紀錄
                print("log insert error:",i["abnormal_no"],lv,e)
    print(f"{datetime.now().isoformat()} scan complete, new notification levels={sent}")

if __name__=="__main__":
    main()
