# Changelog

このファイルはMADO LOOPの利用者向け変更点を記録します。日付は、ownerがrelease metadataを確定するまで付与しません。

## 1.0.0

Production release candidateとして、以下を実装しました。

- 明示的な `$mado-loop` 呼び出しと、schema-v1.1の決定的production router
- `ORCHESTRATOR → SPECIALISTS → ENGINE / ASSET TOOLS → PROOF SYSTEM` の責務分離
- Godot 4.x adapter、固定したGodot Skill snapshot、実Godot fixtureによるP0–P5 proof runner
- creative、game UI、reference-to-UI、sprite、pixel-art、asset integration、gameplay/playtestのproduction guidance
- Pillow / NumPyベースの決定的sprite processingと、ffmpeg / ffprobeを使う証拠処理
- AI Creole handoff、FIELD NOTES policy、project safety、completion contract
- vendor payloadとlicenseを含む、payload-only・ZIP Slip防御付き・byte-reproducible package
- Windows PowerShell 5.1 / PowerShell 7対応のtransactional install、reinstall、upgrade、明示downgrade、rollback、ownership-safe uninstall
- Windows / Ubuntu向けGitHub Actions定義。routing、unit、sprite、Godot integration、P0–P5、package、install、licenseを必須gateとし、成功時だけartifactを公開
- third-party attributionと固定upstream commitの記録

### Pending evidence and limitations

- GitHub Actions workflowは静的構造とローカル契約を検証済みですが、hosted runner上での成功実績はまだ確認されていません。
- Windows 11 / Godot 4.7.2 stableがprimary release gateです。Godot 4.6は互換scope、Linux / macOSはbest effortで、1.0 CIにmacOS hosted gateはありません。
- deterministic ZIPは現在のWindows / Python / zlib環境で反復byte identityを実証済みです。異なるzlib version間のbyte identityは独立には実証していません。
- first-party codeのroot licenseはowner未選択です。vendored third-party codeのlicenseだけが各notice/license fileに明記されています。
