# Changelog

このファイルはMADO LOOPの利用者向け変更点を記録します。日付は、ownerがrelease metadataを確定するまで付与しません。

## 1.0.0

Production release candidateとして、以下を実装しました。

- 明示的な `$mado-loop` 呼び出しと、schema-v1.1の決定的production router
- `ORCHESTRATOR → SPECIALISTS → ENGINE / ASSET TOOLS → PROOF SYSTEM` の責務分離
- OpenRouterをprimary external worker hub、明示許可したEmpero freeをpublic-only opportunistic lane、OpenAI-compatible local endpointをsecret laneとして扱うbounded worker provider router
- worker responseをuntrusted proposalとして扱い、provider/model分離、public/private/secret sensitivity、OpenRouter ZDR/data-collection制約、logged-free明示consentを適用するdelegation contract
- `architect` / `implementer` / `test_writer` を並列fan-outし、`reviewer` でfan-inするfirst-party Parallel Worker Swarm。失敗隔離、決定的role順、bounded concurrency、credential-redacted result、`proof_status: UNPROVEN` を固定
- task domainとbounded complexityから `architect` / `recon` / gameplay・UI・asset specialists / `implementer` / `test_writer` / `release_auditor` を決定的に編成するAdaptive Worker Swarm。role/tier別provider/model profile、assignmentごとのsensitivity enforcement、recursive spawning禁止、release audit時のimplicit implementer除外を実装
- Godot 4.x adapter、固定したGodot Skill snapshot、実Godot fixtureによるP0–P5 proof runner
- creative、game UI、reference-to-UI、sprite、pixel-art、asset integration、gameplay/playtestのproduction guidance
- Pillow / NumPyベースの決定的sprite processingと、ffmpeg / ffprobeを使う証拠処理
- AI Creole handoff、FIELD NOTES policy、project safety、completion contract
- vendor payloadとlicenseを含む、payload-only・ZIP Slip防御付き・byte-reproducible package
- Windows PowerShell 5.1 / PowerShell 7対応のtransactional install、reinstall、upgrade、明示downgrade、rollback、ownership-safe uninstall
- Windows / Ubuntu向けGitHub Actions定義。routing、unit、sprite、Godot integration、P0–P5、package、install、licenseを必須gateとし、成功時だけartifactを公開
- third-party attributionと固定upstream commitの記録

### Evidence and limitations

- production head `ae7b79fcda779811429014abd5d7c6b2b5a7b367` の [GitHub Actions run 32967083386](https://github.com/madowaku/mado-loop/actions/runs/32967083386) は、Windows/Ubuntuの全必須gateとartifact publishまで成功しました。公開artifactは107件の安全な`ZIP_STORED` memberを含み、Linux CI buildとWindows local buildのbyte-identical SHA-256は `89397f793e04af0e6657f98a02a861a565af23ce2cbf652d9b49cecea44e71fc` です。
- worker provider calls and swarm calls are optional and are not part of deterministic release proof. CI unit tests validate selection, sensitivity, adaptive composition, role/tier model routing, concurrency, failure isolation, deterministic fan-in ordering, and proof-authority invariants without making billable or logged external model calls.
- Windows 11 / Godot 4.7.2 stableがprimary release gateです。Godot 4.6は互換scope、Linux / macOSはbest effortで、1.0 CIにmacOS hosted gateはありません。
- deterministic ZIPは`ZIP_STORED`で構築するためzlib versionに依存せず、Linux CI buildとWindows local buildでも同一SHA-256を確認しています。
- first-party codeのroot licenseはowner未選択です。vendored third-party codeのlicenseだけが各notice/license fileに明記されています。
