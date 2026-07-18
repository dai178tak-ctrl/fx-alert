# USD/JPY 急変通知（GitHub Actions + Discord）

GitHub Actionsが15分ごとにUSD/JPYを確認し、急変または指定レート到達時だけDiscordへ通知します。PCやiPhoneが停止していても動作します。

## 初期設定（約10分）

1. このフォルダーの中身を、新しいGitHubリポジトリへアップロードします。
2. Discordで通知先チャンネルを開き、`チャンネルの編集` → `連携サービス` → `ウェブフック` → `新しいウェブフック` を選び、URLをコピーします。
3. GitHubリポジトリで `Settings` → `Secrets and variables` → `Actions` → `New repository secret` を開きます。
4. 名前を `DISCORD_WEBHOOK_URL`、値をDiscordのウェブフックURLにして保存します。
5. GitHubの `Actions` タブでワークフローを有効化します。
6. `FX alert` → `Run workflow` を押して動作確認します。手動実行時は、条件未達でもテスト通知が届きます。

## 初期の通知条件

- 15分で0.50円以上変動
- 1時間で0.80円以上変動
- 前日比1.50%以上変動
- 同じ方向の急変通知は60分間抑制
- 5,000ドルを円転した場合の概算金額を表示

GitHubのスケジュール実行は混雑時に数分以上遅れる場合があります。銀行・証券会社の提示レートとはスプレッドや更新時刻の違いにより一致しません。

## 目標レートを設定する

リポジトリの `Settings` → `Secrets and variables` → `Actions` → `Variables` → `New repository variable` で追加します。

| Name | 例 | 意味 |
|---|---:|---|
| `TARGET_HIGH` | `155.0` | この値以上で通知 |
| `TARGET_LOW` | `145.0` | この値以下で通知 |
| `USD_AMOUNT` | `5000` | 円換算するドル金額 |
| `MOVE_15M_JPY` | `0.5` | 15分の変動幅 |
| `MOVE_1H_JPY` | `0.8` | 1時間の変動幅 |
| `MOVE_DAILY_PCT` | `1.5` | 前日比の変動率 |
| `COOLDOWN_MINUTES` | `60` | 同方向通知の抑制時間 |

値を登録しなければ初期値が使われます。`TARGET_HIGH` と `TARGET_LOW` は未登録で問題ありません。

## 通知されないとき

- `Actions`の実行履歴を開き、赤いエラーがないか確認します。
- Secret名が正確に `DISCORD_WEBHOOK_URL` になっているか確認します。
- Discordのウェブフックを再作成した場合はSecretも更新します。
- GitHubは長期間リポジトリの活動がないと、スケジュールを自動停止する場合があります。

## データと安全性

- DiscordのウェブフックURLはコードに書かず、GitHub Secretに保存します。
- ウェブフックURLを他人に見せたり、公開リポジトリへ直接貼り付けたりしないでください。
- 本ツールは参考情報用です。実際の両替・売買判断には金融機関の提示レートを確認してください。

