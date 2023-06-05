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
ETC_MESSAGE = ["その他"]

# 返答メッセージ
TAIKIN_MESSAGE_OK = "今日もおつかれさま！！"
TAIKIN_MESSAGE_NG = "「たいきん」で退勤登録できます🙏🏻"

# S3設定値
BUCKET_NAME = "go-home-now"
s3_client = boto3.client('s3')

# ログレベル設定
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# タイムゾーン時差
DIFF_JST_FROM_UTC = 9

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

        total_res = datetime.datetime.strptime("00:00", '%H:%M')
        taikin_time = dt_now.strftime("%H:%M")
        taikin_time_date = datetime.datetime.strptime(taikin_time, '%H:%M')

        # 退勤時間から総休憩時間を計算
        logger.info('clac kadou time')
        for time_res in dic_res.values():
            time_res_s_date = datetime.datetime.strptime(time_res['res_s'], '%H:%M')
            time_res_e_date = datetime.datetime.strptime(time_res['res_e'], '%H:%M')
            if taikin_time_date >= time_res_e_date:
                res_time_delta = time_res_e_date - time_res_s_date
                total_res = total_res + res_time_delta
                logger.info('res total -> ' + total_res.strftime('%H:%M'))

        # 始業時間セット（9:00固定）
        shigyo_time = datetime.datetime.strptime("09:00", '%H:%M')

        # 稼働時間計算（退勤時間 - 始業時間）
        kadou_time_delta = taikin_time_date - shigyo_time

        # 休憩時間をtimedelta型へ変換
        total_res_delta = total_res - datetime.datetime.strptime("00:00", '%H:%M')

        # 総稼働時間を計算（timedelta型 -> 秒数 -> int型）
        kadou_time = int(kadou_time_delta.total_seconds() - total_res_delta.total_seconds())

        # 総稼働時間を計算（秒数 -> 時間:分）
        kadou_time_hour, remainder = divmod(kadou_time, 3600)
        kadou_time_min, sec = divmod(remainder, 60)
        kadou_time_time = datetime.time(hour=kadou_time_hour,minute=kadou_time_min)

        kadou_total = kadou_time_time.strftime('%H:%M')

        # 退勤時間JSON上書き
        add_body = {
            dt_now.strftime("%Y-%m-%d"):
                {
                    "TaikinTime": taikin_time,
                    "TotalTime": kadou_total
                }
        }
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
                message = message + "\n" + time_res + ":" + str(kadou[time_res]["TaikinTime"])

        message = message + "\nだよー"

        return message

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

    try:
        # list-backupフォルダへリストを移動
        s3_client.copy_object(Bucket=BUCKET_NAME, 
                              Key=copy_to_path, 
                              CopySource={'Bucket': BUCKET_NAME, 'Key': copy_from_path}
                              )
        
        return "ファイルリセットしたよ"

    except Exception as e:
        return "エラー発生！ : " + str(e)

# -----------------------------
#  設定ファイル修正
# -----------------------------
def fix_setting(s3_client, userID, message):
    logger.info('fix setting_file')

    # 改行コードでリスト化[99:99〜99:99,99:99〜99:99,99:99〜99:99]
    list_fix_time = message.splitlines()

    # 修正後時間
    fix_time = {}
    i = 1

    # リストループ[99:99〜99:99]
    for ls in list_fix_time:
        # 時間を「〜」でリスト化[99:99,99:99]
        list_fix_res = ls.split("~")
        if len(list_fix_res) != 2:
            logger.info('入力形式エラー -> ' + str(list_fix_res))
            return "99:99〜99:99形式じゃないよ！" + str(list_fix_res)
        # 99:99
        for ls_time in list_fix_res:
            if re.match("\d\d:\d\d", ls_time) is None:
                logger.info('入力文字エラー -> ' + ls_time)
                return "入力文字に問題アリ！" + ls_time
        # エラーなければdict化
        add_body = {    
                        "res" + i:
                        {
                            "res_s": list_fix_res[0],
                            "res_e": list_fix_res[1]
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

    return "更新完了🙆‍♀️"


# ================================
# LINE
# ================================
def send_line(userID, message, reply_token):
    logger.info("--- 個別メッセージ配信：" + message + " ---")
    line_bot_api.reply_message(reply_token, TextSendMessage(text = message))
    logger.info("--- 個別メッセージ配信完了 ---")

def send_template(message_template, reply_token):
    logger.info("--- テンプレメッセージ配信：" + message_template + " ---")
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
                                        label='なにもしない',
                                        display_text='なにもしない',
                                        data='done'
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

    body = event['body']

    # ---------------
    #  通常応答
    # ---------------
    @handler.add(MessageEvent, message=TextMessage)
    def on_message(line_event):
        # リクエスト読み込み
        userID = json.loads(event['body'])['events'][0]['source']['userId']
        message = json.loads(event['body'])['events'][0]['message']['text']
        reply_token = json.loads(event['body'])['events'][0]['replyToken']

        logger.info("normal_mode")

        # リクエストメッセージ判定
        if message in GO_HOME:
            # S3バケット内にユーザーファイルが存在するかチェック
            check_file_result = check_file(s3_client, userID, 1)

            # ユーザーファイル無 -> ファイル新規作成
            if check_file_result == False:
                make_new_file(s3_client, userID, 1)

            # 現時間取得
            dt_now = datetime.datetime.utcnow() + datetime.timedelta(hours=DIFF_JST_FROM_UTC)

            # ユーザーファイル編集
            reply = edit_userFile(userID, dt_now)
        
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
        
        elif message == ETC_MESSAGE:
            reply = reply_template(0)
            send_template(reply)
            return 0
        
        # 休憩時間修正
        elif message[:4] == "休憩時間":
            reply = fix_setting(s3_client, userID)
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
            
            reply = """👇🏻のように、頭に「休憩時間」をつけて、休憩時間を教えてね！

                       休憩時間
                       12:00〜13:00
                       17:30〜18:00
                       20:00〜20:25
                    """
            
            send_line(userID, reply, reply_token)
            return 0
        
        # --- 設定ファイル作成モード ---
        elif message == "create_setting":
            make_new_file(s3_client, userID, 2)
            reply = "設定ファイル作ったよー\n" + "もう一度せっていちぇんじしてね"
            send_line(userID, reply, reply_token)
            return 0
        
        handler.handle(body, signature)
        return 0

