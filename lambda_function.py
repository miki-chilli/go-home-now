# *********************************
#  go-home-now
# *********************************
import logging
import datetime
import json
import boto3
from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import TextSendMessage
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

# LINE アクセストークン
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

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
    
        return "今日もおつかれさま！！"
    
    except Exception as e:
        return "エラーが発生しました : " + str(e)

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
def check_file(s3_client, userId):
    response = s3_client.list_objects_v2(
        Bucket=BUCKET_NAME,
    )

    if response['KeyCount'] == 0:
        return False
    
    s3_contents = response["Contents"]
    for s3_content in s3_contents:
        logger.info("s3_content Key: " + str(s3_content.get("Key")))

        if s3_content.get("Key") == userId + ".json":
            if s3_content.get("Size") == 0:
                # 空ファイル(0byte)だった場合
                logger.info("User's File is 0byte! -> " + userId + ".json")
                return False
            
            logger.info("Get User's File! -> " + userId + ".json")
            return True

    logger.info("No User's File! -> " + userId + ".json")
    return False

# --- S3ファイル新規作成 ---
def make_new_file(s3_client, userId):

    body_text = {"user": str(userId)}
    logger.info(str(body_text))
    logger.info(type(body_text))

    s3_client.put_object(
        Bucket = BUCKET_NAME,
        Key = userId + ".json",
        Body = json.dumps(body_text)
    )

    logger.info("make new file! userId: " + str(userId))

# ================================
# LINE
# ================================
def send_line(userID, message, reply_token):
    logger.info("--- 個別メッセージ配信：" + message + " ---")
    line_bot_api.reply_message(reply_token, TextSendMessage(text = message))
    logger.info("--- 個別メッセージ配信完了 ---")

# ================================
# Lambda メイン
# ================================
def lambda_handler(event, context):
    logger.info("get go home now!")

    # リクエスト読み込み
    userID = json.loads(event['body'])['events'][0]['source']['userId']
    message = json.loads(event['body'])['events'][0]['message']['text']
    reply_token = json.loads(event['body'])['events'][0]['replyToken']

    # リクエストメッセージ判定
    if message in GO_HOME:
        # S3バケット内にユーザーファイルが存在するかチェック
        check_file_result = check_file(s3_client, userID)

        # ユーザーファイル無 -> ファイル新規作成
        if check_file_result == False:
            make_new_file(s3_client, userID)

        # 現時間取得
        dt_now = datetime.datetime.utcnow() + datetime.timedelta(hours=DIFF_JST_FROM_UTC)

        # ユーザーファイル編集
        reply = edit_userFile(userID, dt_now)
    
    elif message in LIST_MESSAGE:
        # S3バケット内にユーザーファイルが存在するかチェック
        check_file_result = check_file(s3_client, userID)

         # ユーザーファイル無 -> エラー
        if check_file_result == False:
            reply = "たいきん登録がないよ😭"

        # ユーザーファイル出力
        reply = get_list(userID)
            

    else:
        reply = TAIKIN_MESSAGE_NG
    
    # LINEメッセージ送信
    send_line(userID, reply, reply_token)