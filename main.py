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

# 環境変数の読み込み
SLACK_URL       = os.environ['slack_url']
SLACK_CHANNEL   = os.environ['slack_channel']
RE_EXCLUDE_WORD = os.environ['re_exclude_word']

# ------------------------------------------------------------------------------
# Class & Function
# ------------------------------------------------------------------------------
def cwl_post_slack(log_group, log_stream, log_messages):
    """CloudWatchLogsからのアラートをSlackで通知します。

    あまり汎用性はなく、この関数内にてSlackに送る
    CloudWatchLogs用のフォーマット生成をしています。

    Args:
        log_group(str): ロググループ名
        log_stream(str): ログストリーム名
        log_messages(str): ログの内容

    Returns:
        response_body(str): slackへpostした結果
    """
    title = ':rotating_light: CloudWatchLogsにてアラートを検知しました。確認をお願いします。'
    fileds = [
        {
            'title': 'logGroup',
            'value': log_group,
            'short': False
        },
        {
            'title': 'logStream',
            'value': log_stream,
            'short': False
        },
        {
            'title': 'logMessages',
            'value': log_messages,
            'short': False
        }
    ]

    data = {
        'username': 'CloudWatch Logs',
        'icon_emoji': ':robot_face:',
        'channel': SLACK_CHANNEL,
        'attachments':  [{
            'title': title,
            'color': 'danger',
            'footer': 'ログ監視のため復旧通知はありません',
            'fields': fileds
        }]
    }

    method  = 'POST'
    headers = { 'Content-Type': 'application/json; charset=utf-8' }
    data    = json.dumps(data).encode('utf-8')

    request = urllib.request.Request(url=SLACK_URL, data=data, method=method, headers=headers)

    with urllib.request.urlopen(request) as response:
        response_body = response.read().decode('utf-8')
    return response_body

def decode_gzipbase64(data):
    """gzipされてbase64エンコードされた引数をデコード&解凍して返します。

     CloudWatchLogs Subscriptions でフィルタされたレコードはKinesisストリームを介して
     Lambda の event オブジェクトに以下のようなJSON で入ってきます。
         {
             "awslogs": {
                 "data": "~~~~~~~~~~~~~~~"(gzipされてbase64エンコードされている)
             }
         }
     そのため event['awslogs']['data']を引数として渡せば欲しい情報が取得できます。

    Args:
        data(str): gzipされてbase64でエンコードされた文字列

    Returns:
       json_data():
    """
    decoded_data = base64.b64decode(data)
    json_data = json.loads(zlib.decompress(decoded_data, 16+zlib.MAX_WBITS))
    return json_data


def create_log_param(data):
    """Slack通知に必要な情報を抽出して返します。

    Args:
        data(): 引数の説明

    Returns:
       log_group(str):
       log_stream(str):
       log_messages_markdown(str):
    """
    log_group  = data['logGroup']
    logging.info('log_group: {}'.format(log_group))
    log_stream = data['logStream']
    logging.info('log_stream: {}'.format(log_stream))

    log_events            = data['logEvents']
    log_messages_list     = [i['message'] for i in log_events]
    logging.info('log_messages_list: {}'.format(log_messages_list))
#    log_messages_str      = '\n'.join(log_messages_list)
#    log_messages_markdown = '```\n{}\n```'.format(log_messages_str)

    return (log_group, log_stream, log_messages_list)


def neglect_line_that_include_exclude_word(input_list, exclude_word):
    """除外語を含む行を排除します。

    Args:
        input_list(list): 引数の説明
        exclude_word(str):

    Returns:
       log_group(str):
       log_stream(str):
       log_messages_markdown(str):
    """
    reg_exclude = re.compile(exclude_word)

    neglect_list = []
    output_list  = []

    for line in input_list:
        if reg_exclude.search(line):
            neglect_list.append(line)
        else:
            output_list.append(line)

    logging.info('neglect_list: {}'.format(neglect_list))
    logging.info('output_list: {}'.format(output_list))
    return output_list

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def lambda_handler(event, context):
    try:
        logging.info('lambda_handler start')
        logging.info('Event: {}'.format(json.dumps(event)))

        # gzip圧縮&base64エンコードされている部分をデコード
        event_decode = decode_gzipbase64(event['awslogs']['data'])

        # デコードされた情報から通知に必要な情報を作成
        log_group, log_stream, log_messages_list = create_log_param(event_decode)

        # ログメッセージリストから除外語を含む行を削除
        log_messages_list = neglect_line_that_include_exclude_word(
                                log_messages_list, RE_EXCLUDE_WORD
                            )

        # ログメッセージリストが空だったら
        if not log_messages_list:
            logging.info('No notification because "log_messages_list" is empty.')
        else:
            # ログメッセージリストを1行に文字列連結
            log_messages_str      = '\n'.join(log_messages_list)
            # markdown用の装飾を追加
            log_messages_markdown = '```\n{}\n```'.format(log_messages_str)
            # Slack通知
            res = cwl_post_slack(
                      log_group,
                      log_stream,
                      log_messages_markdown
                  )

            logging.info('post_slack_response: {}'.format(res))

        logging.info('lambda_handler Normal end')
    except Exception as error:
        logging.info('lambda_handler Abnormal end')
        logging.error(error)
        raise error
