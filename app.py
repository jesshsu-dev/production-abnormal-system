import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client, Client

APP_TITLE = "生產異常通報系統"
TZ = ZoneInfo("Asia/Taipei")

st.set_page_config(
    page_title=f"{APP_TITLE} V1.1 Enterprise",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container{padding-top:1rem;padding-bottom:2rem;max-width:1500px}
[data-testid="stSidebar"]{min-width:245px;max-width:245px}
div[data-testid="stMetric"]{border:1px solid #e5e7eb;border-radius:14px;padding:12px;background:#fff}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:14px 16px;background:#fff;
box-shadow:0 1px 3px rgba(0,0,0,.04);margin-bottom:10px}
.status-green{background:#e8f7ee;color:#137a3d;padding:5px 10px;border-radius:999px;font-weight:700}
.status-blue{background:#e8f0ff;color:#1456cc;padding:5px 10px;border-radius:999px;font-weight:700}
.status-yellow{background:#fff6d8;color:#a66b00;padding:5px 10px;border-radius:999px;font-weight:700}
.status-red{background:#ffe7e7;color:#c51f1f;padding:5px 10px;border-radius:999px;font-weight:700}
.status-gray{background:#eef1f5;color:#4b5563;padding:5px 10px;border-radius:999px;font-weight:700}
.small{font-size:.88rem;color:#64748b}
.app-title{font-size:2rem;font-weight:800;line-height:1.5;padding:.45rem 0 .45rem 0;margin:0;overflow:visible;color:#1f2937}
/* Fix Streamlit page titles with CJK text / emoji being vertically clipped */
div[data-testid="stHeadingWithActionElements"]{overflow:visible!important;padding-top:.30rem!important;padding-bottom:.30rem!important;}
div[data-testid="stHeadingWithActionElements"] h1{line-height:1.45!important;padding-top:.18rem!important;padding-bottom:.22rem!important;margin-top:0!important;margin-bottom:.35rem!important;overflow:visible!important;}
@media(max-width:768px){
 .block-container{padding-left:.7rem;padding-right:.7rem;padding-top:.5rem}
 [data-testid="stSidebar"]{min-width:220px;max-width:220px}
 div[data-testid="column"]{min-width:100%!important;flex:1 1 100%!important}
 .stButton button{width:100%}
}
</style>
""", unsafe_allow_html=True)

MAIN_CAUSES = ["人","機","料","法","測","環"]
CAUSE_CATEGORIES = ["人員異常","文件異常","物料異常","設備異常","流程異常","環境異常","設計異常"]
SUB_CAUSES = [
    "環境異常(停電.地震.火災工安)","HSF 檢測不符(RoHS)","客訴異常","工傷事件",
    "物料(原)異常","電性功能異常","半成品組測異常","成品包裝異常","設備及治具異常",
    "程式異常","流程異常","流程卡異常","SOP 異常","其他(說明)"
]
PROCESS_METHODS = [
    "立即維修","隔離/Hold","重工/返工","設備維修","治具更換","報廢","特採",
    "退料/退貨","補料/換料","流程修正/防呆","設計/規格變更","供應商篩選",
    "廠內篩選","其他(說明)"
]
PROGRESS = ["待受理","處理中","待確認","已結案"]


def secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


def new_client(access_token=None, refresh_token=None) -> Client:
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error("尚未設定 SUPABASE_URL / SUPABASE_ANON_KEY。請依 README 設定 .streamlit/secrets.toml。")
        st.stop()
    cli = create_client(url, key)
    if access_token and refresh_token:
        cli.auth.set_session(access_token, refresh_token)
    return cli


def authed_client():
    if "access_token" not in st.session_state:
        return None
    try:
        cli = new_client(st.session_state.access_token, st.session_state.refresh_token)
        session = cli.auth.get_session()
        if session and session.access_token:
            st.session_state.access_token = session.access_token
            st.session_state.refresh_token = session.refresh_token
        return cli
    except Exception:
        st.session_state.clear()
        return None


def fetch_profile(cli):
    uid = st.session_state.get("user_id")
    if not uid:
        return None
    r = cli.table("profiles").select("*").eq("id", uid).single().execute()
    return r.data


def iso_to_local(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z","+00:00"))
    return dt.astimezone(TZ)


def local_text(value):
    dt = iso_to_local(value) if isinstance(value, str) else value
    return dt.strftime("%Y/%m/%d %H:%M:%S") if dt else "-"


def elapsed_minutes(report_time):
    dt = iso_to_local(report_time)
    return max(0, int((datetime.now(TZ) - dt).total_seconds() // 60))


def escalation_info(row):
    if row.get("receive_time"):
        return ("已接收","gray",0,"停止未接收催辦")
    m = elapsed_minutes(row["report_time"])
    if m >= 120: return ("嚴重逾時","red",5,"最高主管")
    if m >= 60:  return ("重大逾時","yellow",4,"上級主管")
    if m >= 15:  return ("主管催辦","blue",3,"單位主管")
    if m >= 10:  return ("等待接收","green",2,"工程/品保相關人員")
    if m >= 5:   return ("等待接收","green",1,"工程/品保相關人員")
    return ("等待接收","green",0,"尚未催辦")


def render_status(text, color):
    st.markdown(f'<span class="status-{color}">{text}</span>', unsafe_allow_html=True)


def can_handle(role):
    return role in ["工程","品保","主管","管理員"]


def can_close(role):
    return role in ["品保","主管","管理員"]


def can_admin(role):
    return role in ["主管","管理員"]


def login_view():
    st.markdown(f'<div class="app-title">🚨 {APP_TITLE}</div>', unsafe_allow_html=True)
    st.caption("V1.1 Enterprise｜Streamlit + Supabase｜電腦 / 手機皆可登入")
    c1,c2,c3 = st.columns([1,1.3,1])
    with c2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("使用者登入")
        email = st.text_input("公司 Email / 登入 Email")
        password = st.text_input("密碼", type="password")
        if st.button("登入系統", type="primary", use_container_width=True):
            try:
                cli = new_client()
                res = cli.auth.sign_in_with_password({"email":email.strip(),"password":password})
                if not res.session or not res.user:
                    st.error("登入失敗。")
                else:
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token
                    st.session_state.user_id = res.user.id
                    st.rerun()
            except Exception as e:
                st.error(f"登入失敗：{e}")
        st.caption("帳號由 Supabase Auth 管理；正式版不在程式碼內保存密碼。")
        st.markdown("</div>", unsafe_allow_html=True)


def logout(cli):
    try:
        cli.auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.rerun()


def fetch_incidents(cli, filters=None):
    q = cli.table("incidents").select("*").order("report_time", desc=True)
    if filters:
        for op, col, val in filters:
            if op == "eq": q = q.eq(col,val)
            elif op == "is": q = q.is_(col,val)
    return q.execute().data or []


def get_incident(cli, no):
    r = cli.table("incidents").select("*").eq("abnormal_no",no).single().execute()
    return r.data


def home_page(cli):
    st.title("🏠 首頁總覽")
    rows = fetch_incidents(cli)
    today = datetime.now(TZ).date()
    waiting=blue=yellow=red=today_count=0
    for r in rows:
        if iso_to_local(r["report_time"]).date() == today:
            today_count += 1
        if not r.get("receive_time"):
            waiting += 1
            _, color, _, _ = escalation_info(r)
            blue += color=="blue"; yellow += color=="yellow"; red += color=="red"

    a,b,c,d,e=st.columns(5)
    a.metric("等待接收",waiting); b.metric("主管催辦(藍)",blue)
    c.metric("重大逾時(黃)",yellow); d.metric("嚴重逾時(紅)",red); e.metric("今日通報總數",today_count)

    st.subheader("即時訊息")
    if not rows:
        st.info("目前尚無異常通報。"); return
    for r in rows[:30]:
        status,color,level,target=escalation_info(r)
        m = elapsed_minutes(r["report_time"]) if not r.get("receive_time") else None
        c1,c2,c3,c4=st.columns([1.2,2,4.5,1.5])
        with c1: render_status(status,color)
        with c2: st.write(f"**{r['abnormal_no']}**")
        with c3:
            wait = f"｜已等待 {m} 分鐘" if m is not None else ""
            st.write(f"{r.get('model') or '-'}｜{r['abnormal_type']}｜{r.get('abnormal_desc') or '-'}{wait}")
        with c4: st.caption(f"通知 {level}/5｜{target}")


def report_page(cli, profile):
    st.title("🚨 異常通報")
    st.caption("送出後由 Supabase 自動產生異常編號，並開始計算未接收時間。")
    with st.form("report_form", clear_on_submit=True):
        c1,c2=st.columns(2)
        with c1:
            abnormal_type=st.selectbox("異常類型 *",SUB_CAUSES)
            work_order=st.text_input("工單單號 *")
            model=st.text_input("生產機種 *")
            work_qty=st.number_input("工單數量 *",min_value=0,step=1)
            defect_qty=st.number_input("不良數量 *",min_value=0,step=1)
        with c2:
            material_no=st.text_input("物料料號")
            process_name=st.text_input("製程別 *",placeholder="例：組裝測試")
            st.text_input("通報人員",value=profile["display_name"],disabled=True)
            st.text_input("通報時間",value=datetime.now(TZ).strftime("%Y/%m/%d %H:%M"),disabled=True)
        abnormal_desc=st.text_area("異常描述 *",height=130)
        submit=st.form_submit_button("送出異常通報",type="primary",use_container_width=True)

    if submit:
        if not all([work_order.strip(),model.strip(),process_name.strip(),abnormal_desc.strip()]):
            st.error("請完整填寫 * 必填欄位。"); return
        try:
            data={
                "abnormal_type":abnormal_type,"work_order":work_order.strip(),"model":model.strip(),
                "work_qty":int(work_qty),"defect_qty":int(defect_qty),"material_no":material_no.strip(),
                "process_name":process_name.strip(),"reporter_id":profile["id"],
                "reporter_name":profile["display_name"],"abnormal_desc":abnormal_desc.strip(),
                "process_progress":"待受理"
            }
            res=cli.table("incidents").insert(data).execute()
            no=res.data[0]["abnormal_no"] if res.data else "(已建立)"
            st.success(f"異常通報完成，異常編號：{no}")
        except Exception as e:
            st.error(f"新增失敗：{e}")


def receive_page(cli, profile):
    st.title("📥 異常接收")
    rows=cli.table("incidents").select("*").is_("receive_time","null").eq("process_progress","待受理").order("report_time").execute().data or []
    if not rows:
        st.success("目前沒有待接收案件。"); return
    no=st.selectbox("選擇待接收異常",[r["abnormal_no"] for r in rows])
    row=next(r for r in rows if r["abnormal_no"]==no)
    status,color,level,target=escalation_info(row); render_status(status,color)
    st.markdown(f"""<div class="card">
    <b>異常類型：</b>{row['abnormal_type']}<br>
    <b>工單單號：</b>{row.get('work_order') or '-'}　<b>生產機種：</b>{row.get('model') or '-'}<br>
    <b>不良數量：</b>{row.get('defect_qty',0)}　<b>通報人員：</b>{row.get('reporter_name','-')}<br>
    <b>通報時間：</b>{local_text(row['report_time'])}<br>
    <b>異常描述：</b>{row.get('abnormal_desc') or '-'}
    </div>""",unsafe_allow_html=True)
    if st.button("確認接收",type="primary",use_container_width=True):
        try:
            cli.table("incidents").update({
                "receiver_id":profile["id"],"receiver_name":profile["display_name"],
                "receive_time":datetime.now(TZ).isoformat(),"process_progress":"處理中"
            }).eq("id",row["id"]).is_("receive_time","null").execute()
            st.success("已接收；未接收催辦計時立即停止。"); st.rerun()
        except Exception as e: st.error(f"接收失敗：{e}")


def reply_page(cli, profile):
    st.title("↩️ 異常回覆")
    rows=cli.table("incidents").select("*").eq("process_progress","處理中").is_("reply_time","null").order("receive_time").execute().data or []
    if not rows:
        st.success("目前沒有待回覆案件。"); return
    no=st.selectbox("選擇待回覆異常",[r["abnormal_no"] for r in rows])
    row=next(r for r in rows if r["abnormal_no"]==no)
    st.markdown(f"""<div class="card">
    <b>異常編號：</b>{row['abnormal_no']}<br><b>工單：</b>{row.get('work_order') or '-'}　
    <b>機種：</b>{row.get('model') or '-'}<br><b>接收人員：</b>{row.get('receiver_name') or '-'}　
    <b>接收時間：</b>{local_text(row.get('receive_time'))}<br><b>異常描述：</b>{row.get('abnormal_desc') or '-'}
    </div>""",unsafe_allow_html=True)
    with st.form("reply_form"):
        c1,c2=st.columns(2)
        with c1:
            method=st.selectbox("處理方式 *",PROCESS_METHODS)
            main=st.selectbox("主類異常 *",MAIN_CAUSES)
            category=st.selectbox("要因分類 *",CAUSE_CATEGORIES)
        with c2:
            sub=st.selectbox("次類異常 *",SUB_CAUSES)
            total=st.number_input("總不良數 *",min_value=0,step=1,value=int(row.get("defect_qty") or 0))
            st.text_input("回覆人員",value=profile["display_name"],disabled=True)
        root=st.text_area("原因分析 *",height=150)
        submit=st.form_submit_button("送出異常回覆",type="primary",use_container_width=True)
    if submit:
        if not root.strip(): st.error("請填寫原因分析。"); return
        try:
            t=datetime.now(TZ).isoformat()
            cli.table("incidents").update({
                "replier_id":profile["id"],"replier_name":profile["display_name"],
                "reply_time":t,"process_progress":"待確認","process_method":method,
                "finish_time":t,"main_cause":main,"cause_category":category,"sub_cause":sub,
                "total_defect_qty":int(total),"root_cause":root.strip()
            }).eq("id",row["id"]).eq("process_progress","處理中").execute()
            st.success("回覆完成，案件已轉為「待確認」。"); st.rerun()
        except Exception as e: st.error(f"回覆失敗：{e}")


def close_page(cli, profile):
    st.title("✅ 異常結案")
    rows=cli.table("incidents").select("*").eq("process_progress","待確認").order("reply_time").execute().data or []
    if not rows:
        st.success("目前沒有待結案案件。"); return
    no=st.selectbox("選擇待結案異常",[r["abnormal_no"] for r in rows])
    r=next(x for x in rows if x["abnormal_no"]==no)
    st.markdown(f"""<div class="card">
    <b>異常編號：</b>{r['abnormal_no']}<br><b>回覆人員：</b>{r.get('replier_name') or '-'}　
    <b>回覆時間：</b>{local_text(r.get('reply_time'))}<br><b>處理方式：</b>{r.get('process_method') or '-'}<br>
    <b>主類異常：</b>{r.get('main_cause') or '-'}　<b>要因分類：</b>{r.get('cause_category') or '-'}<br>
    <b>次類異常：</b>{r.get('sub_cause') or '-'}<br><b>總不良數：</b>{r.get('total_defect_qty') or 0}<br>
    <b>原因分析：</b>{r.get('root_cause') or '-'}
    </div>""",unsafe_allow_html=True)
    ok=st.checkbox("品保已確認內容正確，可結案")
    if st.button("異常結案",type="primary",use_container_width=True,disabled=not ok):
        try:
            cli.table("incidents").update({
                "process_progress":"已結案","closer_id":profile["id"],
                "closer_name":profile["display_name"],"close_time":datetime.now(TZ).isoformat()
            }).eq("id",r["id"]).eq("process_progress","待確認").execute()
            st.success("案件已結案。"); st.rerun()
        except Exception as e: st.error(f"結案失敗：{e}")


def search_page(cli):
    st.title("🔎 關鍵查詢")
    c1,c2,c3=st.columns(3)
    keyword=c1.text_input("關鍵字",placeholder="異常編號/工單/機種/料號/人員")
    progress=c2.selectbox("處理進度",["全部"]+PROGRESS)
    abnormal_type=c3.selectbox("異常類型",["全部"]+SUB_CAUSES)
    rows=fetch_incidents(cli)
    df=pd.DataFrame(rows)
    if df.empty:
        st.info("尚無資料。"); return
    if keyword.strip():
        k=keyword.strip().lower()
        cols=["abnormal_no","work_order","model","material_no","reporter_name","receiver_name","replier_name","abnormal_desc"]
        mask=pd.Series(False,index=df.index)
        for c in cols:
            if c in df: mask |= df[c].fillna("").astype(str).str.lower().str.contains(k,regex=False)
        df=df[mask]
    if progress!="全部": df=df[df["process_progress"]==progress]
    if abnormal_type!="全部": df=df[df["abnormal_type"]==abnormal_type]
    display_cols=["abnormal_no","abnormal_type","work_order","model","defect_qty","reporter_name","report_time",
                  "receiver_name","process_progress","replier_name","main_cause","cause_category","total_defect_qty"]
    display_cols=[c for c in display_cols if c in df]
    out=df[display_cols].copy()
    if "report_time" in out: out["report_time"]=out["report_time"].map(local_text)
    st.dataframe(out,use_container_width=True,hide_index=True)


def history_page(cli):
    st.title("📋 查詢紀錄")
    rows=fetch_incidents(cli)
    if not rows: st.info("尚無資料。"); return
    no=st.selectbox("異常編號",[r["abnormal_no"] for r in rows])
    r=next(x for x in rows if x["abnormal_no"]==no)
    st.subheader("完整處理履歷")
    st.markdown(f"""<div class="card"><b>① 異常通報</b><br>
異常編號：{r['abnormal_no']}<br>異常類型：{r['abnormal_type']}<br>工單單號：{r.get('work_order') or '-'}<br>
生產機種：{r.get('model') or '-'}<br>工單數量：{r.get('work_qty',0)}　不良數量：{r.get('defect_qty',0)}<br>
物料料號：{r.get('material_no') or '-'}　製程別：{r.get('process_name') or '-'}<br>
通報人員：{r.get('reporter_name') or '-'}　通報時間：{local_text(r.get('report_time'))}<br>
異常描述：{r.get('abnormal_desc') or '-'}</div>
<div class="card"><b>② 異常接收</b><br>接收人員：{r.get('receiver_name') or '-'}<br>
接收時間：{local_text(r.get('receive_time'))}<br>處理進度：{r['process_progress']}</div>
<div class="card"><b>③ 異常回覆</b><br>回覆人員：{r.get('replier_name') or '-'}<br>
處理方式：{r.get('process_method') or '-'}<br>完成時間：{local_text(r.get('finish_time'))}<br>
主類異常：{r.get('main_cause') or '-'}　要因分類：{r.get('cause_category') or '-'}<br>
次類異常：{r.get('sub_cause') or '-'}<br>總不良數：{r.get('total_defect_qty') or 0}<br>
原因分析：{r.get('root_cause') or '-'}</div>
<div class="card"><b>④ 異常結案</b><br>結案人員：{r.get('closer_name') or '-'}<br>
結案時間：{local_text(r.get('close_time'))}<br>狀態：{r['process_progress']}</div>""",unsafe_allow_html=True)

    st.subheader("Email / LINE 催辦紀錄")
    logs=cli.table("notification_logs").select("*").eq("incident_id",r["id"]).order("level").execute().data or []
    if logs:
        ldf=pd.DataFrame(logs)
        if "notify_time" in ldf: ldf["notify_time"]=ldf["notify_time"].map(local_text)
        st.dataframe(ldf,use_container_width=True,hide_index=True)
    else: st.caption("尚無催辦紀錄。")


def stats_page(cli):
    st.title("📊 異常統計")
    df=pd.DataFrame(fetch_incidents(cli))
    if df.empty: st.info("尚無資料。"); return
    c1,c2,c3,c4=st.columns(4)
    c1.metric("異常總數",len(df))
    c2.metric("待受理",int((df["process_progress"]=="待受理").sum()))
    c3.metric("處理中/待確認",int(df["process_progress"].isin(["處理中","待確認"]).sum()))
    c4.metric("已結案",int((df["process_progress"]=="已結案").sum()))
    st.subheader("異常類型")
    st.bar_chart(df["abnormal_type"].value_counts())
    st.subheader("主類異常")
    st.bar_chart(df["main_cause"].fillna("未分類").value_counts())


def admin_page(cli, profile):
    st.title("⚙️ 系統管理")
    st.subheader("五級未接收催辦規則")
    rules=cli.table("notification_rules").select("*").order("level").execute().data or []
    rdf=pd.DataFrame(rules)
    if not rdf.empty:
        st.dataframe(rdf[["level","threshold_minutes","color","target_label","enabled"]],
                     use_container_width=True,hide_index=True)

    st.subheader("通知對象設定")
    profiles=cli.table("profiles").select("id,display_name,role,department,email,line_user_id,active").eq("active",True).order("display_name").execute().data or []
    if not profiles:
        st.warning("目前沒有可設定的人員。"); return
    name_to_id={f"{p['display_name']}｜{p['department']}｜{p['role']}":p["id"] for p in profiles}
    current=cli.table("notification_members").select("level,user_id").execute().data or []
    by_level={i:[] for i in range(1,6)}
    id_to_label={v:k for k,v in name_to_id.items()}
    for m in current:
        if m["user_id"] in id_to_label: by_level[m["level"]].append(id_to_label[m["user_id"]])

    with st.form("members_form"):
        selections={}
        labels={1:"第1次 >5分鐘：工程/品保",2:"第2次 >10分鐘：工程/品保",
                3:"第3次 >15分鐘：單位主管",4:"第4次 >1小時：上級主管",5:"第5次 >2小時：最高主管"}
        for lv in range(1,6):
            selections[lv]=st.multiselect(labels[lv],list(name_to_id.keys()),default=by_level[lv])
        save=st.form_submit_button("儲存通知對象",type="primary",use_container_width=True)
    if save:
        try:
            cli.table("notification_members").delete().gte("level",1).lte("level",5).execute()
            payload=[]
            for lv,items in selections.items():
                payload += [{"level":lv,"user_id":name_to_id[x]} for x in items]
            if payload: cli.table("notification_members").insert(payload).execute()
            st.success("通知對象已更新。"); st.rerun()
        except Exception as e: st.error(f"儲存失敗：{e}")

    st.subheader("使用者名冊")
    st.dataframe(pd.DataFrame(profiles),use_container_width=True,hide_index=True)
    st.info("人員角色、Email、LINE user ID 建議由管理員在 Supabase Table Editor 的 profiles 表維護。")


def main():
    if "access_token" not in st.session_state:
        login_view(); return
    cli=authed_client()
    if not cli:
        login_view(); return
    try:
        profile=fetch_profile(cli)
    except Exception as e:
        st.error(f"無法讀取使用者資料：{e}")
        st.info("請確認已執行 supabase_schema.sql，且 Auth 使用者已有 profiles 紀錄。")
        return
    if not profile or not profile.get("active",True):
        st.error("帳號未啟用。"); return

    role=profile["role"]
    with st.sidebar:
        st.markdown("## UPRtek")
        st.caption("群燿光學股份有限公司")
        st.markdown("---")
        st.write(f"👤 **{profile['display_name']}**")
        st.caption(f"{profile.get('department','')}｜{role}")
        options=["首頁總覽","異常通報","異常接收","異常回覆","異常結案","即時訊息","關鍵查詢","查詢紀錄","異常統計"]
        if can_admin(role): options.append("系統管理")
        page=st.radio("功能選單",options,label_visibility="collapsed")
        st.markdown("---")
        if st.button("登出",use_container_width=True): logout(cli)

    if page in ["首頁總覽","即時訊息"]: home_page(cli)
    elif page=="異常通報": report_page(cli,profile)
    elif page=="異常接收":
        if can_handle(role):
            receive_page(cli, profile)
        else:
            st.error("此功能限工程／品保相關人員。")
    elif page=="異常回覆":
        if can_handle(role):
            reply_page(cli, profile)
        else:
            st.error("此功能限工程／品保相關人員。")
    elif page=="異常結案":
        if can_close(role):
            close_page(cli, profile)
        else:
            st.error("此功能限品保人員。")
    elif page=="關鍵查詢": search_page(cli)
    elif page=="查詢紀錄": history_page(cli)
    elif page=="異常統計": stats_page(cli)
    elif page=="系統管理": admin_page(cli,profile)

if __name__=="__main__":
    main()
