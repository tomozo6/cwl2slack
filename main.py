# ------------------------------------------------------------------------------
# モジュールのインポート
# ------------------------------------------------------------------------------
# 標準モジュール
import base64
import json
import logging
import os
import re
import zlib
import urllib.request

# ------------------------------------------------------------------------------
# 前処理
# ------------------------------------------------------------------------------
# ログ設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ------------------------------------------------------------------------------
# 変数設定
# ------------------------------------------------------------------------------
# Slack関連
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
SLACK_CHANNEL = os.environ["SLACK_CHANNEL"]

# アラート対象外用語
RE_EXCLUDE_WORD = os.getenv("RE_EXCLUDE_WORD")

# Lambda名
FUNCTION_NAME = os.getenv("FUNCTION_NAME", "cwl2slack")


# ------------------------------------------------------------------------------
# Class & Function
# ------------------------------------------------------------------------------
def cwl_post_slack(log_group: str, log_stream: str, log_message: str) -> str:
    """CloudWatchLogsのアラートをSlackに通知します

    Args:
        log_group(str): CloudWatchLogsのロググループ名
        log_stream(str): CloudWatchLogsのログストリーム名
        log_message(str): CloudWatchLogsのログメッセージ

    Returns:
        response_body(str): Slack通知のレスポンスボディ
    """
    title = ":rotating_light: CloudWatchLogsにてアラートを検知しました"
    fileds = [
        {"title": "logGroup", "value": log_group, "short": False},
        {"title": "logStream", "value": log_stream, "short": False},
        {"title": "logMessage", "value": log_message, "short": False},
    ]

    data = {
        "username": "CloudWatch Logs",
        "icon_emoji": ":robot_face:",
        "channel": SLACK_CHANNEL,
        "attachments": [
            {
                "title": title,
                "color": "danger",
                "footer": f"post by {FUNCTION_NAME}",
                "fields": fileds,
            }
        ],
    }

    method = "POST"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url=SLACK_WEBHOOK_URL, data=data, method=method, headers=headers
    )

    with urllib.request.urlopen(request) as response:
        response_body = response.read().decode("utf-8")
    return response_body


def decode_gzipbase64(data: str) -> str:
    """gzipされてbase64エンコードされた引数をデコード&解凍して返します

    CloudWatchLogs Subscriptions でフィルターされたレコードは Kinesis ストリームを介して
    Lambda の event オブジェクトに下記のような json で入ってきます。

    {
        "awslogs": {
        "data": "~~~~~~~~~~~~~~~"(gzipされてbase64エンコードされている)
        }
    }

    そのため event['awslogs']['data'] を引数として本関数に渡せば欲しい情報が取得できます。

    Args:
        data(str): gzip圧縮&base64エンコードされた文字列

    Returns:
        json_data(dict): デコードされた情報
    """
    decoded_data = base64.b64decode(data)
    json_data = json.loads(zlib.decompress(decoded_data, 16 + zlib.MAX_WBITS))
    logging.info(f"{json_data=}")
    return json_data


def create_log_param(data: str):
    """Slack通知に必要な情報を抽出して返します

    Args:
        data(str): デコードされた文字列

    Returns:
        log_group(str): CloudWatchLogsのロググループ名
        log_stream(str): CloudWatchLogsのログストリーム名
        log_messages(list): CloudWatchLogsのログメッセージ
    """
    log_group = data["logGroup"]
    logging.info(f"{log_group=}")
    log_stream = data["logStream"]
    logging.info(f"{log_stream=}")

    log_events = data["logEvents"]
    log_messages = [i["message"] for i in log_events]
    logging.info(f"{log_messages}")

    return (log_group, log_stream, log_messages)


def neglect_line_that_include_exclude_word(input_list, exclude_word):
    """除外語を含む行を排除します

    Args:
        input_list(list): ログメッセージリスト
        exclude_word(str): 除外語

    Returns:
        output_list(list): 除外語を含まないログメッセージリスト


    Examples:

        >>> input_list = [
        ...     "2020-01-01 00:00:00,000 [INFO] test1",
        ...     "2020-01-01 00:00:00,000 [INFO] test2",
        ...     "2020-01-01 00:00:00,000 [INFO] test3",
        ... ]
        >>> exclude_word = "test2"
        >>> neglect_line_that_include_exclude_word(input_list, exclude_word)
        ['2020-01-01 00:00:00,000 [INFO] test1', '2020-01-01 00:00:00,000 [INFO] test3']
    """
    reg_exclude = re.compile(exclude_word)

    neglect_list = []
    output_list = []

    for line in input_list:
        if reg_exclude.search(line):
            neglect_list.append(line)
        else:
            output_list.append(line)

    logging.info("neglect_list: {}".format(neglect_list))
    logging.info("output_list: {}".format(output_list))
    return output_list


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def handler(event, context) -> None:
    try:
        logging.info("Start function.")
        logging.info("Event: {}".format(json.dumps(event)))

        # gzip圧縮&base64エンコードされている部分をデコード
        event_decode = decode_gzipbase64(event["awslogs"]["data"])

        # デコードされた情報から通知に必要な情報を作成
        log_group, log_stream, log_messages = create_log_param(event_decode)

        # ログメッセージリストから除外語を含む行を削除
        if (RE_EXCLUDE_WORD is None) or (len(RE_EXCLUDE_WORD) == 0):
            pass
        else:
            log_messages = neglect_line_that_include_exclude_word(
                log_messages, RE_EXCLUDE_WORD
            )

        # ログメッセージリストが空だったら
        if not log_messages:
            logging.info('No notification. Because "log_messages" is empty.')
        else:
            # ログメッセージリストを1行に文字列連結
            log_messages_str = "\n".join(log_messages)
            # markdown用の装飾を追加
            log_messages_markdown = "```\n{}\n```".format(log_messages_str)
            # Slack通知
            resp = cwl_post_slack(log_group, log_stream, log_messages_markdown)

            logging.info(f"{resp=}")

    except Exception as e:
        logging.error(e)
        raise e
