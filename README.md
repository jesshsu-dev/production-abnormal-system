# 生產異常通報系統 V1.1 Enterprise

架構：**Streamlit + Supabase Auth + Supabase PostgreSQL + RLS + Email/LINE Worker**

## 已完成
- 電腦與手機瀏覽器登入
- Supabase Auth 帳密登入
- PostgreSQL 正式多人共用資料庫
- RLS 資料存取控制
- 生產：異常通報
- 工程/品保：異常接收
- 工程/品保：異常回覆
- 品保：異常結案
- 即時訊息 / 關鍵查詢 / 完整履歷 / 異常統計
- 主類異常：人、機、料、法、測、環
- 要因分類 / 次類異常 / 處理方式
- 5 / 10 / 15 / 60 / 120 分鐘五級未接收催辦
- 綠 / 綠 / 藍 / 黃 / 紅逾時燈號
- Email + LINE 推播 worker
- 主管可在網頁設定每一級通知對象
- Email / LINE 通知紀錄保存

## A. 建立 Supabase
1. 建立 Supabase Project。
2. 打開 **SQL Editor**。
3. 將 `supabase_schema.sql` 全部貼上並執行。
4. 到 **Authentication > Users** 建立公司使用者（Email + Password）。
5. 到 **Table Editor > profiles** 修改：
   - `display_name`
   - `role`：生產 / 工程 / 品保 / 主管 / 管理員
   - `department`
   - `email`
   - `line_user_id`
6. 至少將一位使用者 `role` 改成 `管理員`。

## B. Streamlit Secrets
複製：
`.streamlit/secrets.toml.example`
成：
`.streamlit/secrets.toml`

填入：
```toml
SUPABASE_URL = "..."
SUPABASE_ANON_KEY = "..."
```

**不要把 secrets.toml 上傳到 GitHub。**

## C. 本機執行
```bash
pip install -r requirements.txt
streamlit run app.py
```

同一 Wi-Fi 內，手機可以使用電腦區網 IP，例如：
`http://192.168.1.100:8501`

若部署到 Streamlit Community Cloud / 公司雲端主機，手機及電腦都可直接由 HTTPS 網址登入。

## D. 五級自動通知
規則預設：
1. > 5 分鐘未接收：綠色，工程/品保
2. > 10 分鐘未接收：綠色，工程/品保
3. > 15 分鐘未接收：藍色，單位主管
4. > 60 分鐘未接收：黃色，上級主管
5. > 120 分鐘未接收：紅色，最高主管

工程/品保按下「確認接收」後，`receive_time` 被寫入，worker 後續便不再催辦。

## E. Email / LINE worker
`worker.py` 必須放在可信任的後端或排程器，因為它需要 Supabase Service Role Key。

先設定環境變數（參考 `.env.example`），再執行：
```bash
python worker.py
```

正式環境建議 **每 1 分鐘執行一次**。

Linux cron 例：
```cron
* * * * * cd /opt/production_abnormal && /usr/bin/python3 worker.py >> worker.log 2>&1
```

### Email
worker 支援一般 SMTP STARTTLS 或 SMTP SSL。
Microsoft 365 / 公司 SMTP 的實際主機、驗證政策，請依公司 IT 設定。

### LINE
使用 LINE Messaging API 的 Channel access token，以及每位接收人的 `line_user_id`。
請在 profiles 填好 `line_user_id`，再於系統管理頁設定第 1～5 級通知人員。

## F. 安全重點
- Streamlit 只使用 Supabase **Anon Key**。
- `SUPABASE_SERVICE_ROLE_KEY` 僅給 `worker.py` 的可信任伺服器使用。
- Service Role Key 不可放到瀏覽器、公開 GitHub 或前端程式。
- 資料表已啟用 RLS。
- Auth 密碼由 Supabase Auth 管理，不存於 incidents / profiles。

## G. 檔案
- `app.py`：Streamlit 主系統
- `supabase_schema.sql`：資料表、Trigger、RLS、通知規則
- `worker.py`：五級 Email + LINE 自動催辦
- `requirements.txt`
- `.streamlit/secrets.toml.example`
- `.env.example`
