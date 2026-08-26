# MADO LOOP 1.0

MADO LOOP は、Godot 4.x のゲーム開発を「作った」で終わらせず、実装、統合、実行、観察、修正、証明まで一続きにする Codex Skill です。依頼を決定的に分類し、必要な専門知識とエンジン／アセットツールだけを選び、P0–P5 の証拠に基づいて結果を報告します。

MADO LOOP は自動では起動しません。Codex で明示的に `$mado-loop` を呼び出したときだけ使われます。

## Philosophy

基本ループは `UNDERSTAND → ROUTE → MAKE → INTEGRATE → RUN → INSPECT → VERIFY → FIX → PROVE` です。専門家の主張だけを完成証明にせず、実際のプロジェクトで観測できる証拠へ段階的に引き上げます。必須依存や必須検証が欠けた場合は green にせず、`UNKNOWN` または `FAIL` として正直に止まります。

アーキテクチャは責務を4層に分離します。

```text
ORCHESTRATOR
  ↓ 依頼の分類、経路選択、受入判定
SPECIALISTS
  ↓ ドメイン別の制作・設計ガイダンス
ENGINE / ASSET TOOLS
  ↓ 決定的なGodot操作・画像処理・統合
PROOF SYSTEM
     P0–P5の検査、証拠集約、結果判定
```

詳細は [routing architecture](.agents/skills/mado-loop/references/routing/architecture.md) と [capability registry](.agents/skills/mado-loop/references/routing/capability-registry.md) を参照してください。

## Requirements

- 主対象: Windows 11
- リリース基準: Godot 4.7.2 stable
- 互換対象: Godot 4.6
- Linux / macOS: best effort（1.0 CI は Windows と Ubuntu を検証。macOS は hosted gate 未実施）
- Python 3（CI 基準は Python 3.12）
- Godotを使う実行・検証経路では、利用可能なGodot 4.x実行ファイル
- 動画・音声やフレーム証拠を扱う経路では `ffmpeg` と `ffprobe`
- sprite processorを使う経路では Pillow と NumPy（1.0 CI 固定値は Pillow 11.3.0 / NumPy 2.3.2）
- release installer: Windows PowerShell 5.1 または PowerShell 7

ImageGen、外部画像エディター、追加Skillなどは任意能力です。MADO LOOPが自動インストールすることはありません。

## Install / update / uninstall

Release ZIP と、このリポジトリの `scripts/install.ps1` を用意します。以下はリポジトリのルートで実行する例です。

Windows PowerShell 5.1:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -PackagePath .\dist\mado-loop-1.0.0.zip -Mode Release -Version 1.0.0
```

PowerShell 7:

```powershell
pwsh.exe -NoProfile -File ./scripts/install.ps1 -PackagePath ./dist/mado-loop-1.0.0.zip -Mode Release -Version 1.0.0
```

既定のインストール先は `$HOME/.agents/skills/mado-loop` です。`-Version` を省略した場合はリポジトリの `VERSION` を読みます。テストや隔離環境では `-HomePath <path>` を指定できます。

同一バージョンの再実行は reinstall、新しいバージョンは upgrade です。古いバージョンへの変更は既定で拒否され、意図した downgrade のみ `-AllowDowngrade` を加えます。

```powershell
pwsh.exe -NoProfile -File ./scripts/install.ps1 -PackagePath ./dist/mado-loop-older.zip -Mode Release -Version 0.9.0 -AllowDowngrade
```

uninstall:

```powershell
pwsh.exe -NoProfile -File ./scripts/uninstall.ps1
```

別HOMEから削除する場合だけ `-HomePath <path>` を指定します。uninstaller は ownership marker とファイルhashを確認し、変更されたファイルや利用者が追加したファイルを残します。

## Invoke and route

Codexへの依頼で明示的に呼びます。

```text
$mado-loop プレイヤーのダッシュを実装し、実際に操作して証明して
```

暗黙起動はありません。router は依頼を `CODE`, `GAMEPLAY`, `UI`, `SPRITE`, `IMAGE`, `ANIMATION`, `ASSET_INTEGRATION`, `REFERENCE_TO_UI`, `PIXEL_ART`, `PLAYTEST`, `RELEASE` に分類します。複数ドメインでは `MIXED` を付加し、専門ガイダンス → ツール処理 → Godot統合 → 観察／playtest → proof の順で最小経路を構成します。

分類器だけを確認する場合:

```powershell
python .agents/skills/mado-loop/scripts/classify_task.py --pretty "UIを実装して操作確認する"
```

### Production pipelines

- Creative: `IMAGE` を起点にart directionを定め、利用可能で許可された画像能力を選び、生成物をGodot側で検証します。
- UI: `UI` → game UI guidance → Godot実装 → layout・legibility・interactionの観察。
- Image-to-UI: `REFERENCE_TO_UI + UI + ASSET_INTEGRATION`。参照をコピーせず構造・意図へ分解してUIへ再構成します。
- Sprite: `SPRITE + ANIMATION + ASSET_INTEGRATION`。sprite guidance、決定的な正規化／slice／atlas処理、Godot importとruntime確認を通します。
- Pixel art: `PIXEL_ART` を追加し、整数scale、grid、補間などpixel-safe制約を適用します。

## P0–P5 proof ladder

| Level | 証明するもの |
| --- | --- |
| P0 — Static Proof | syntax、import、parseを含むstatic checks |
| P1 — Runtime Proof | boot／startup、runtime error、runtime readiness |
| P2 — Layout Proof | UI／layout、static visual、screenshot inspection |
| P3 — Behavior Proof | deterministicなgameplay／input／state-transition behavior |
| P4 — Visual Motion Proof | animation／motion／capture／temporal evidenceとproof sheet／video |
| P5 — Release Proof | export／artifact／release audit |

高いlevelは関連する下位gateを含みます。修正後は影響を受けたgateと下流gateを再実行します。Release依頼では新機能を暗黙に追加せず、必要なP0–P5、export、必須content、設定、配布物を監査します。詳細は [proof ladder](.agents/skills/mado-loop/references/proof/proof-ladder.md) と [completion contract](.agents/skills/mado-loop/references/proof/completion-contract.md) にあります。

## Example workflows

| Workflow | 依頼例 | Expected route |
| --- | --- | --- |
| Gameplay | `$mado-loop RESTマスでHPが上限を超えないよう修正して` | `GAMEPLAY → Godot → P3` |
| Sprite + Gameplay | `$mado-loop 京都ボスに狐火の攻撃アニメーションを追加して` | `SPRITE → ART DIRECTION → IMAGE GENERATION → NORMALIZE → GODOT INTEGRATION → GAMEPLAY → P3 → P4` |
| UI | `$mado-loop ボス戦HUDをもっと見やすくして` | `GAME UI → GODOT UI → P2` |
| Image-to-UI | `$mado-loop この画像を参考に戦闘HUDを作り直して` | `REFERENCE ANALYSIS → GAME UI → IMPLEMENT → CAPTURE → COMPARE → P2/P4` |
| Pixel Art | `$mado-loop このキャラの4方向歩行を今のpixel styleに合わせて追加して` | `PIXEL ART PROFILE → SPRITE PIPELINE → NORMALIZE → GODOT → P4` |
| Release | `$mado-loop このAPKをGoogle Play提出候補として監査して` | `RELEASE → P5` |

## Dependencies, package, and CI

Godot操作は固定した `godot-skill` snapshotをfirst-party adapter越しに利用し、sprite処理は固定した `agent-sprite-forge` の一部を同様に包みます。upstream snapshotは直接編集しません。出典とライセンスは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) に記録されています。

配布物は `.agents/skills/mado-loop/` だけを `mado-loop/` rootへ格納します。entry順、timestamp、permission、compression、path separatorを固定し、同じtreeからの反復buildをbyte-identicalにします。

```powershell
python scripts/package.py --output dist/mado-loop-1.0.0.zip --json
```

[CI workflow](.github/workflows/ci.yml) は routing、unit、sprite、Windows/Ubuntu Godot integration、P0–P5、deterministic package、Windows dual-shell install、third-party attributionを必須gateにし、全gate成功時だけZIP artifactを公開します。production head `ae7b79fcda779811429014abd5d7c6b2b5a7b367` では [GitHub Actions run 32967083386](https://github.com/madowaku/mado-loop/actions/runs/32967083386) がWindows/Ubuntuの全必須gateとartifact publishまで成功しました。公開artifactは107件の安全な`ZIP_STORED` memberを含み、Linux CI buildとWindows local buildのbyte-identical SHA-256は `89397f793e04af0e6657f98a02a861a565af23ce2cbf652d9b49cecea44e71fc` です。

## Troubleshooting

- Godot、`ffmpeg`、`ffprobe`、Pillow、NumPyなど必須能力がない: 必須checkはPASSになりません。該当能力を自動導入せず、欠落と必要な次の操作を報告します。
- `destination collision` / ownership marker error: インストール先にMADO LOOP管理外のtreeがあります。上書きしません。内容を確認し、利用者自身が退避先を決めてください。
- dirty / modified / unexpected files: upgradeは既存treeを保護して拒否します。必要な変更を別の場所へ退避してから再実行してください。
- install中の失敗: publish前の旧版はrollbackされます。restoreまで失敗した場合、`.agents/skills/.mado-loop.backup.<id>` が唯一の有効backupとして保存されるため、削除せず内容を確認してください。
- uninstall後にtreeが残る: 変更済みmanaged fileまたはuntracked fileを保護した結果です。自動削除されません。
- optional capabilityがない: warning / optional `SKIPPED` になり得ます。勝手なplugin・Skill・editorのinstallや、別能力への無言の置換はしません。

## Licensing

vendored third-party codeのnoticeと完全なlicense textは保持されています。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) と各vendor directoryを参照してください。

**このリポジトリのfirst-party codeに適用するroot licenseは、ownerによってまだ選択されていません。** third-party部分のMIT licenseを、MADO LOOP全体の利用許諾と解釈しないでください。
