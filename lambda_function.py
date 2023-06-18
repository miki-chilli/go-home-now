# *********************************
#  go-home-now
# *********************************
import logging
import datetime
import json
import re
import boto3
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import LineBotApiError
from linebot.models import (MessageEvent, TextMessage, PostbackEvent,
                            TemplateSendMessage, ButtonsTemplate, PostbackAction,
                            TextSendMessage
                            )
import os

# ログレベル設定
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# タイムゾーン時差
DIFF_JST_FROM_UTC = 9
JST = datetime.timezone(datetime.timedelta(hours=+DIFF_JST_FROM_UTC), 'JST')

# 受け取りメッセージ
GO_HOME = ["go-home", "退勤", "たいきん"]
LIST_MESSAGE = ["list", "リスト"]
RESET_MESSAGE = ["りせっと"]
ETC_MESSAGE = ["その他", "そのた"]

# 返答メッセージ
TAIKIN_MESSAGE_OK = "今日もおつかれさま！！"
TAIKIN_MESSAGE_NG = "「たいきん」で退勤登録できます🙏🏻"

# S3設定値
BUCKET_NAME = "go-home-now"
s3_client = boto3.client('s3')

# ログレベル設定
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 環境変数
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")

# LINE アクセストークン
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
# LINE ハンドラー
handler = WebhookHandler(CHANNEL_SECRET)

# ================================
#  S3
# ================================
def edit_userFile(userID, dt_now):
    try:
        # 稼働・休憩時間のJSONファイル取得
        s3_object_res = s3_client.get_object(
            Bucket = BUCKET_NAME,
            Key = "time/" + userID + "_res.json"
        )

        # 休憩時間をdict化
        dic_res = json.loads(s3_object_res['Body'].read())
        logger.info("rest time -> " + str(dic_res))

        # 退勤時間記入JSONファイル取得
        s3_client_taikin = s3_client.get_object(
            Bucket = BUCKET_NAME,
            Key = userID + ".json"
        )

        # 稼働時間JSONをdict化
        kadou = json.loads(s3_client_taikin['Body'].read())
        logger.info("kadou time -> " + str(kadou))

        # 設定ファイル取得
        s3_client_setting = s3_client.get_object(
                Bucket = BUCKET_NAME,
                Key = "time/" + userID + "_conf.json"
            )
        setting = json.loads(s3_client_setting['Body'].read())
        work_time = datetime.datetime.strptime(setting['work_time'], '%H:%M')

        total_res = datetime.datetime.strptime("00:00", '%H:%M')
        taikin_time = dt_now.strftime("%H:%M")
        taikin_time_date = datetime.datetime.strptime(taikin_time, '%H:%M')

        # 退勤時間から総休憩時間を計算
        logger.info('clac kadou time')

        # 休憩時間計算
        add_body = kadou_time_calc(dt_now, taikin_time, dic_res, setting)
        if add_body == 9:
            return "エラー発生🥲"
        
        logger.info('add_body -> ' + str(add_body))
        logger.info(type(add_body))

        # 稼働時間ファイル更新
        body_text = dict(kadou, **add_body)

        # 読み込んだJSONファイルに追記
        logger.info("update file -> userId: " + str(userID) + "body: " + str(body_text))

        #ファイルの更新
        s3_client.put_object(
            Bucket = BUCKET_NAME,
            Key = userID + ".json",
            Body = json.dumps(body_text)
        )
    
        return TAIKIN_MESSAGE_OK
    
    except Exception as e:
        return "エラーが発生しました : " + str(e)

# ---------------------------
#  退勤時間修正
# ---------------------------
def fix_taikinTime(s3_client, userID, message, dt_now):
    logger.info("退勤時間修正")

    # 入力文字列チェック
    #yyyy/mm/dd HH:MM
    if re.match("\d{4}/\d{2}/\d{2}", message[4:14]) is None \
        or re.match("\d\d:\d\d", message[15:]) is None:
            return "「退勤修正YYYY/MM/DD HH:MM」で入力してね！ -> " + str(message) 
    
    # 修正する日付 (YYYY-mm-dd)
    fix_date = message[4:14].replace('/','-')
    fix_date = datetime.datetime.strptime(fix_date, '%Y-%m-%d')
    logger.info("fix_date -> " + str(fix_date))
    # 修正後の時間
    fix_time = message[15:]
    logger.info("fix_time -> " + str(fix_time))

    # 勤怠ファイル取得
    s3_client_kadou = s3_client.get_object(
            Bucket = BUCKET_NAME,
            Key = userID + ".json"
        )
    kadou = json.loads(s3_client_kadou['Body'].read())

    # 設定ファイル取得
    s3_client_setting = s3_client.get_object(
            Bucket = BUCKET_NAME,
            Key = "time/" + userID + "_conf.json"
        )
    setting = json.loads(s3_client_setting['Body'].read())

    # 稼働・休憩時間のJSONファイル取得
    s3_object_res = s3_client.get_object(
        Bucket = BUCKET_NAME,
        Key = "time/" + userID + "_res.json"
    )

    # 休憩時間をdict化
    time_res_setting = json.loads(s3_object_res['Body'].read())

    # 休憩時間計算
    add_body = kadou_time_calc(fix_date, fix_time, time_res_setting, setting)
    if add_body == 9:
        return "エラー発生🥲"
    
    logger.info('add_body -> ' + str(add_body))
    logger.info(type(add_body))

    # 稼働時間ファイル更新
    body_text = dict(kadou, **add_body)
    logger.info("update file -> userId: " + str(userID) + "body: " + str(body_text))

    #ファイルの更新
    s3_client.put_object(
        Bucket = BUCKET_NAME,
        Key = userID + ".json",
        Body = json.dumps(body_text)
    )

    return "稼働時間あっぷでーと🙆‍♀️"


# ---------------------------
#  退勤リスト作成
# ---------------------------
def get_list(userID):
        logger.info('get taikin list')
        # 退勤時間記入JSONファイル取得
        s3_client_taikin = s3_client.get_object(
            Bucket = BUCKET_NAME,
            Key = userID + ".json"
        )
        kadou = json.loads(s3_client_taikin['Body'].read())
        logger.info("kadou time -> " + str(kadou))

        message = "今月の退勤時間は"

        for time_res in kadou.keys():
            if time_res != "user":
                message = message + "\n" + time_res + " " + str(kadou[time_res]["TaikinTime"])

        message = message + "\nだよー"

        return message

# ---------------------------
#  残り可能残業時間計算
# ---------------------------
def calc_ZangyoTime(s3_client, userID):
    try:
        # 稼働時間ファイル取得
        s3_client_taikin = s3_client.get_object(
                Bucket = BUCKET_NAME,
                Key = userID + ".json"
            )
        kadou = json.loads(s3_client_taikin['Body'].read())

        # 設定ファイル取得
        s3_client_setting = s3_client.get_object(
                Bucket = BUCKET_NAME,
                Key = "time/" + userID + "_conf.json"
            )
        setting = json.loads(s3_client_setting['Body'].read())

        # 当月稼働日
        month_kadou_day = int(setting['month_kadou_day'])
        # 定時稼働時間
        work_time = datetime.datetime.strptime(setting['work_time'], '%H:%M')
        # 稼働時間上限
        max_kadou_time = setting['max_kadou_time']

        total_time_sum_s = 0
        over_time_sum =  datetime.datetime.strptime("00:00", '%H:%M')

        # 累計稼働時間取得
        for time_res in kadou.keys():
                if time_res != "user":
                    # 総合計稼働時間
                    total_time = datetime.datetime.strptime(kadou[time_res]["TotalTime"], '%H:%M')
                    # 時間 -> 秒
                    total_time_h = total_time.hour
                    total_time_m = total_time.minute
                    total_time_s = int(datetime.timedelta(hours = total_time_h, minutes= total_time_m).total_seconds())
                    # 秒数加算
                    total_time_sum_s = total_time_sum_s + total_time_s
                    logger.info("h -> " + str(total_time_h))
                    logger.info("m -> " + str(total_time_m))
                    logger.info("total -> " + str(total_time_sum_s))
                    # 秒 -> 時間
                    total_time_sum_h, remainder = divmod(total_time_sum_s, 3600)
                    total_time_sum_m, sec = divmod(remainder, 60)
                    total_time_sum = str(total_time_sum_h).zfill(2) + ":" + str(total_time_sum_m).zfill(2)
                    logger.info("total_time_sum -> " + total_time_sum)
                    # 総残業時間
                    if total_time > work_time:
                        over_time = total_time - work_time
                        over_time_sum = over_time_sum + over_time

        logger.info("累計稼働時間・総残業時間計算完了")
        
        # 残稼働時間計算
        # [ 稼働時間上限(180h) - 累計稼働時間 ]
        # 当月稼働日 × 定時稼働時間（秒）
        work_time_sec = int(datetime.timedelta(hours = work_time.hour, minutes = work_time.minute).total_seconds())
        logger.info("work_time_sec -> " + str(work_time_sec))
        logger.info("month_kadou_day -> " + str(month_kadou_day))
        work_time_month_sec = work_time_sec * month_kadou_day
        logger.info("work_time_month_sec -> " + str(work_time_month_sec))

        # 稼働時間上限（時間 -> 秒） − 累計稼働時間（時間 -> 秒）
        max_kadou_time_sec = int(max_kadou_time) * 3600
        total_kadou_time_sec = int(datetime.timedelta(hours = int(total_time_sum[:2]), minutes = int(total_time_sum[3:])).total_seconds())

        # 残稼働時間（秒）
        diff_kadou_time = max_kadou_time_sec - total_kadou_time_sec
        logger.info("diff_kadou_time -> " + str(diff_kadou_time))

        # 残稼働時間（秒 -> 時間）
        diff_kadou_time_hour, remainder = divmod(diff_kadou_time, 3600)
        diff_kadou_time_min, sec = divmod(remainder, 60)
        diff_total = str(diff_kadou_time_hour).zfill(2) + ":" + str(diff_kadou_time_min).zfill(2)
        logger.info("diff_total -> " + diff_total)

        # 残りの可能な残業時間を計算
        # 稼働時間上限（時間 -> 秒） − 当月定時稼働時間（時間 -> 秒）
        overtime_sec = max_kadou_time_sec - work_time_month_sec
        diff_overtime_sec = overtime_sec - \
                            int(datetime.timedelta(hours = over_time_sum.hour, minutes = over_time_sum.minute).total_seconds())
        logger.info("diff_overtime_sec -> " + str(diff_overtime_sec))

        # 残残業時間（秒 -> 時間）
        diff_overtime_hour, remainder = divmod(diff_overtime_sec, 3600)
        diff_overtime_min, sec = divmod(remainder, 60)
        diff_overtime_time = datetime.time(hour = diff_overtime_hour, minute = diff_overtime_min)
        diff_overtime_total = diff_overtime_time.strftime('%H:%M')
        logger.info("diff_overtime_total -> " + diff_overtime_total)

        # メッセージ組み立て
        message = "総稼働時間 -> " + total_time_sum + "\n"
        message = message + "総残業時間 -> " + over_time_sum.strftime('%H:%M') + "\n"
        message = message + "残り可能稼働時間 -> " + diff_total + "\n"
        message = message + "残り可能残業時間 -> " + diff_overtime_total + "\n"
        message = message + "だよー"

        return message
    
    except Exception as e:
        return "エラーが発生しました : " + str(e)

# ===========================
#  稼働時間計算
# ===========================
# (I)time_date   (datetime)  : 追加更新日付
# (I)taikin_time (string)    : 退勤時間
# (I)time_res_setting (dict) : 休憩設定ファイル
# (I)setting     (dict)      : 設定ファイル
# (O)kadou_calc  (dict)      : 稼働時間
# ===========================
def kadou_time_calc(time_date, taikin_time, time_res_setting, setting):
    # ログレベル設定
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    try:
        logger.info('kadou_time_calc')
        total_res = datetime.datetime.strptime("00:00", '%H:%M')
        taikin_time_date = datetime.datetime.strptime(taikin_time, '%H:%M')

        # 定時就業時間
        work_time = datetime.datetime.strptime(setting['work_time'], '%H:%M')

        # 始業時間
        shigyo_time = datetime.datetime.strptime(setting['start_time'], '%H:%M')

        # 退勤時間から総休憩時間を計算
        logger.info('clac kadou time')

        for time_res in time_res_setting.values():
            time_res_s_date = datetime.datetime.strptime(time_res['res_s'], '%H:%M')
            time_res_e_date = datetime.datetime.strptime(time_res['res_e'], '%H:%M')
            # 休憩時間中の退勤時間は休憩時間を引かない
            if taikin_time_date > time_res_s_date and taikin_time_date >= time_res_e_date:
                res_time_delta = time_res_e_date - time_res_s_date
                total_res = total_res + res_time_delta
                logger.info('res total (over)-> ' + total_res.strftime('%H:%M'))
            # 休憩時間中の退勤時 -> 休憩終了時間 - 退勤時間を休憩時間とする
            elif taikin_time_date > time_res_s_date and taikin_time_date < time_res_e_date:
                res_time_delta = time_res_e_date - taikin_time_date
                total_res = total_res + res_time_delta
                logger.info('res total (in)-> ' + total_res.strftime('%H:%M'))

        # 稼働時間計算（退勤時間 - 始業時間）
        kadou_time_delta = taikin_time_date - shigyo_time

        # 休憩時間をtimedelta型へ変換
        total_res_delta = total_res - datetime.datetime.strptime("00:00", '%H:%M')

        # 総稼働時間を計算（timedelta型 -> 秒数 -> int型）
        kadou_time = int(kadou_time_delta.total_seconds() - total_res_delta.total_seconds())

        # 総稼働時間を計算（秒数 -> 時間:分）
        kadou_time_hour, remainder = divmod(kadou_time, 3600)
        kadou_time_min, sec = divmod(remainder, 60)
        kadou_time_time = datetime.time(hour = kadou_time_hour, minute = kadou_time_min)

        #定時時間より計算時間が小さかったら定時時間にする（同時間かつ分が定時に満たない場合 ※半休考慮）
        if kadou_time_hour == work_time.hour and kadou_time_min <= work_time.minute:
            kadou_time_time = work_time

        kadou_total = kadou_time_time.strftime('%H:%M')

        # 退勤時間dict作成
        add_body = {
            time_date.strftime('%Y-%m-%d'):
                {
                    "TaikinTime": taikin_time,
                    "TotalTime": kadou_total
                }
        }
        logger.info(str(add_body))
        logger.info(type(add_body))
        return add_body
    
    except Exception as e:
        logger.info("エラーが発生しました : " + str(e))
        return 9

# ---------------------------
#  ファイル存在チェック
# --------------------------- 
def check_file(s3_client, userId, intMode):
    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
    )

    if intMode == 1:
        keyName = userId
    elif intMode == 2:
        keyName = "time/" + userId + "_res"

    if response['KeyCount'] == 0:
        return False
    
    s3_contents = response["Contents"]
    for s3_content in s3_contents:
        logger.info("s3_content Key: " + str(s3_content.get("Key")))

        if s3_content.get("Key") == keyName + ".json":
            if s3_content.get("Size") == 0:
                # 空ファイル(0byte)だった場合
                logger.info("User's File is 0byte! -> " + keyName + ".json")
                return False
            
            logger.info("Get User's File! -> " + keyName + ".json")
            return True

    logger.info("No User's File! -> " + keyName + ".json")
    return False

# --- S3ファイル新規作成 ---
def make_new_file(s3_client, userId, intMode):

    body_text = {"user": str(userId)}
    logger.info(str(body_text))
    logger.info(type(body_text))

    # 退勤ファイル
    if intMode == 1:
        keyName = userId
    elif intMode == 2:
        keyName = "time/" + userId + "_res"

        s3_client.put_object(
            Bucket = BUCKET_NAME,
            Key = keyName + ".json",
            Body = json.dumps(body_text)
        )

    logger.info("make new file! userId: " + str(userId))

# ---------------------------
# 　S3ファイルリセット
# ---------------------------
def reset_file(s3_client, userID):
    copy_to_path = "list-backup/" + userID + ".json"
    copy_from_path = userID + ".json"

    logger.info("S3ファイルリセットします")
    try:
        # list-backupフォルダへリストを移動
        s3_client.copy_object(Bucket=BUCKET_NAME, 
                              Key=copy_to_path, 
                              CopySource={'Bucket': BUCKET_NAME, 'Key': copy_from_path}
                              )
        logger.info("S3ファイルリセット完了")
        return "ファイルリセットしたよ"

    except Exception as e:
        return "エラー発生！ : " + str(e)

# -----------------------------
#  設定ファイル修正
# -----------------------------
def fix_setting(s3_client, userID, message, mode):
    logger.info('fix setting_file')

    if mode == 1:
        # 改行コードでリスト化[99:99〜99:99,99:99〜99:99,99:99〜99:99]
        list_fix_time = message.splitlines()

        # 修正後時間
        fix_time = {}
        i = 0

        # リストループ[99:99〜99:99]
        for ls in list_fix_time:
            if i > 0:
                if re.match("\d\d:\d\d〜\d\d:\d\d", ls) is None:
                    logger.info('入力形式エラー -> ' + str(ls))
                    return "99:99〜99:99形式じゃないよ！" + str(ls)
                # エラーなければdict化
                wk_time = ls
                add_body = {    
                                "res" + str(i):
                                {
                                    "res_s": wk_time[:5],
                                    "res_e": wk_time[6:]
                                }
                            }
                fix_time = dict(fix_time, **add_body)

            i = i + 1

        # 休憩時間設定ファイル更新
        s3_client.put_object(
                Bucket = BUCKET_NAME,
                Key = "time/" + userID + "_res.json",
                Body = json.dumps(fix_time)
            )

        logger.info("fix file!: " + str(fix_time))
        reply = "更新完了🙆‍♀️"

    elif mode == 2:
        month_kadou_day = message[4:]
        if month_kadou_day.isnumeric() == False:
            return "数値でおねがい -> " + month_kadou_day
        
        # エラーなければ登録
        add_body = {
            "month_kadou_day": str(month_kadou_day)
        }

        # 設定ファイル取得
        s3_client_setting = s3_client.get_object(
                Bucket = BUCKET_NAME,
                Key = "time/" + userID + "_conf.json"
            )
        setting = json.loads(s3_client_setting['Body'].read())

        body_text = dict(setting, **add_body)

        # 読み込んだJSONファイルに追記
        logger.info("update file -> userId: " + str(userID) + "body: " + str(body_text))

        #ファイルの更新
        s3_client.put_object(
            Bucket = BUCKET_NAME,
            Key = "time/" + userID + "_conf.json",
            Body = json.dumps(body_text)
        )

        reply = "更新完了🙆‍♀️"

    return reply


# ================================
# LINE
# ================================
def send_line(userID, message, reply_token):
    logger.info("--- 個別メッセージ配信：" + message + " ---")
    line_bot_api.reply_message(reply_token, TextSendMessage(text = message))
    logger.info("--- 個別メッセージ配信完了 ---")

def send_template(message_template, reply_token):
    logger.info("--- テンプレメッセージ配信：" + str(message_template) + " ---")
    line_bot_api.reply_message(reply_token, message_template)
    logger.info("--- テンプレメッセージ配信完了 ---")

# ---------------
#  通常応答
# ---------------
def reply_template(intNum):
    if intNum == 0:
        logger.info('--- その他モード ---')
        message_template = TemplateSendMessage(
                            alt_text='どうする？',
                            template=ButtonsTemplate(
                                title='どうする？',
                                text='どうする？',
                                actions=[
                                    PostbackAction(
                                        label='せっていかえる',
                                        display_text='せっていかえる',
                                        data='change_setting'
                                    )
                                    , PostbackAction(
                                        label='リセットする',
                                        display_text='リセットする',
                                        data='reset'
                                    )
                                    , PostbackAction(
                                        label='稼働日数せってい',
                                        display_text='稼働日数せってい',
                                        data='kadou_nissu'
                                    )
                                    , PostbackAction(
                                        label='可能稼働時間ちぇっく',
                                        display_text='可能稼働時間ちぇっく',
                                        data='のこり'
                                    )
                                ]
                            )
                        )

    elif intNum == 1:
        logger.info("--- 設定ファイル修正モード ---")
        message_template = TemplateSendMessage(
                            alt_text='せっていちぇんじ',
                            template=ButtonsTemplate(
                                title='せっていちぇんじ',
                                text='せっていかえる？',
                                actions=[
                                    PostbackAction(
                                        label='かえる',
                                        display_text='かえる',
                                        data='change_setting'
                                    ),
                                    PostbackAction(
                                        label='かえない',
                                        display_text='かえない',
                                        data='done'
                                    )
                                ]
                            )
                        )
        
    elif intNum == 2:
        message_template = TemplateSendMessage(
                            alt_text='設定ファイルなかった…作る？',
                            template=ButtonsTemplate(
                                title='設定ファイルなかった…作る？',
                                text='設定ファイルなかった…作る？',
                                actions=[
                                    PostbackAction(
                                        label='つくる',
                                        display_text='つくる',
                                        data='create_setting'
                                    ),
                                    PostbackAction(
                                        label='つくらない',
                                        display_text='つくらない',
                                        data='done'
                                    )
                                ]
                            )
                        )
    
    return message_template

# ================================
# Lambda メイン
# ================================
def lambda_handler(event, context):
    logger.info("get go home now!")
    logger.info(event)

    # シグネチャー
    signature = event['headers']['x-line-signature']
    logger.info(signature)

    body = event['body']
    logger.info(body)

    # ---------------
    #  通常応答
    # ---------------
    @handler.add(MessageEvent, message=TextMessage)
    def on_message(line_event):
        logger.info(line_event.message.text)
        # リクエスト読み込み
        userID = json.loads(event['body'])['events'][0]['source']['userId']
        message = json.loads(event['body'])['events'][0]['message']['text']
        reply_token = json.loads(event['body'])['events'][0]['replyToken']

        logger.info("normal_mode")

        # 現時間取得
        dt_now = datetime.datetime.utcnow() + datetime.timedelta(hours=DIFF_JST_FROM_UTC)

        # たいきん登録
        if message in GO_HOME:
            # S3バケット内にユーザーファイルが存在するかチェック
            check_file_result = check_file(s3_client, userID, 1)

            # ユーザーファイル無 -> ファイル新規作成
            if check_file_result == False:
                make_new_file(s3_client, userID, 1)

            # ユーザーファイル編集
            reply = edit_userFile(userID, dt_now)

            send_line(userID, reply, reply_token)
            return 0
        
        # リスト出力
        elif message in LIST_MESSAGE:
            # S3バケット内にユーザーファイルが存在するかチェック
            check_file_result = check_file(s3_client, userID, 1)

            # ユーザーファイル無 -> エラー
            if check_file_result == False:
                reply = "たいきん登録がないよ😭"
                send_line(userID, reply, reply_token)
                return 0

            # ユーザーファイル出力
            reply = get_list(userID)
            send_line(userID, reply, reply_token)
            return 0

        # その他モード（Postbackメッセージ送信）
        elif message in ETC_MESSAGE:
            reply = reply_template(0)
            send_template(reply, reply_token)
            return 0
        
        # 休憩時間修正
        elif message[:4] == "休憩時間":
            reply = fix_setting(s3_client, userID, message, 1)
            send_line(userID, reply, reply_token)
            return 0
        
        # 稼働日数修正
        elif message[:4] == "稼働日数":
            reply = fix_setting(s3_client, userID, message, 2)
            send_line(userID, reply, reply_token)
            return 0
        
        # 退勤時間修正
        elif message[:4] == "退勤修正":
            reply = fix_taikinTime(s3_client, userID, message, dt_now)
            send_line(userID, reply, reply_token)
            return 0
        
        else:
            reply = TAIKIN_MESSAGE_NG
            send_line(userID, reply, reply_token)

        return 0
        
    # ---------------
    #  設定モード
    # ---------------
    @handler.add(PostbackEvent)
    def on_postback(line_event):
        logger.info("handle_postback")
        # リクエスト読み込み
        userID = json.loads(event['body'])['events'][0]['source']['userId']
        message = json.loads(event['body'])['events'][0]['postback']['data']
        reply_token = json.loads(event['body'])['events'][0]['replyToken']

        # --- リセットモード ---
        if message == "reset":
            # S3バケット内にユーザーファイルが存在するかチェック
            check_file_result = check_file(s3_client, userID, 1)

            # ユーザーファイル無 -> エラー
            if check_file_result == False:
                reply = "たいきん登録がないよ😭"
                send_line(userID, reply, reply_token)
                return 0
            
            # ファイルリセット
            reply = reset_file(s3_client, userID)
            send_line(userID, reply, reply_token)

        # --- 設定変更モード ---
        elif message == "change_setting":
            # 設定ファイル存在チェック
            check_file_result = check_file(s3_client, userID, 2)

            if check_file_result == False:
                reply = "設定ファイルがないよ😭"
                send_line(userID, reply, reply_token)
                return 0
            
            reply = "👇🏻のように、頭に「休憩時間」をつけて、休憩時間を教えてね！\n"
            reply = reply + "休憩時間\n"
            reply = reply + "12:00〜13:00\n"
            reply = reply + "17:30〜18:00\n"
            reply = reply + "20:00〜20:25\n"
            
            send_line(userID, reply, reply_token)
            return 0
        
        # --- 設定ファイル作成モード ---
        elif message == "create_setting":
            make_new_file(s3_client, userID, 2)
            reply = "設定ファイル作ったよー\n" + "もう一度せっていちぇんじしてね"
            send_line(userID, reply, reply_token)
            return 0
        
        # --- 稼働日数登録モード ---
        elif message == "kadou_nissu":
            reply = "👇🏻のように、頭に「稼働日数」をつけて、稼働日数を教えてね！\n"
            reply = reply + "稼働日数20"
            send_line(userID, reply, reply_token)

        # --- 残り残業時間 ---
        elif message == "のこり":
            reply = calc_ZangyoTime(s3_client, userID)
            send_line(userID, reply, reply_token)
            return 0
        
    handler.handle(body, signature)
    return 0

