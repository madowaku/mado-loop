# Changelog

このファイルはMADO LOOPの利用者向け変更点を記録します。日付は、ownerがrelease metadataを確定するまで付与しません。

## Unreleased

- Orchestration & Verification Protocol (OVP) のfirst-party mutation runtime `ovp_runtime.py` を追加。worker-equivalent disposable preflight、Git worktree isolation、AI Creole Agent Contract、exact-ID mutation receipt、orchestrator-only review/acceptance、merge/cherry-pick integration、schema-v1.1 P0-P5 proof binding、安全cleanupを一つのstate machineとして実装
- OVP mutation workerはassigned worktreeだけを変更してcommitし、`REVIEW_READY`で停止。scope逸脱、dirty/uncommitted result、receipt後のbranch/HEAD差し替え、diff未確認acceptance、integration後のleader HEAD移動をgateで拒否し、既存proposal swarmのread-only / `proof_status: UNPROVEN` contractは維持
- `budget_governor_v2.py` を追加し、OpenRouter Hy3 free / NVIDIA fleet / explicit logged-free / local / Codex Plus LunaをPlus reset pressureとrole qualityで横断routing。selected lane障害時は同じsensitivity policy内の候補へdeterministic automatic fallbackを実行し、worker出力は引き続きproposal-only / `proof_status: UNPROVEN`
- OpenRouter `tencent/hy3-preview:free` をzero-priced bounded worker laneとしてBudget Governor 2.0から利用可能にし、recon/testでは通常時からfree-first、conserve/critical時はimplementation/specialistでもPlusより前へ昇格可能。OpenRouterの既存 `data_collection=deny,zdr=true` policyは維持
- Tencent Hy4 previewのWorkBuddy/CodeBuddy launch promotionはmanual advisory laneとして登録。2026-08-28 launchから2週間という公式告知をconservative cutoffで扱うが、WorkBuddy product entitlementをAPI entitlementへ変換せず、paid Hy4 API fallbackは既定で無効
- Budget Governor 2.0にcontent-free execution ledgerを追加し、role/lane/provider/model/cost class/status/duration/token metadataのみ保存。prompt/completion/credential/API keyは保存しない
- ChatGPT-plan認証済みCodex CLIをAPIキーなしで再利用する `codex_plus_lane.py` を追加。Sol Mediumをparent orchestrator / architect / reviewerとして温存し、Luna xhighをbounded implementation/specialist、Luna highをrecon/testへ割り当て
- Codex Plus pacingをfixed 7-day policyからnext-reset feedback controllerへ更新。Codex `/status` / ChatGPT usage dashboardのcoarse履歴から同一reset windowのremaining-percent burnを学習し、early/manual resetでreset時刻が変わった場合は旧windowのburn historyを持ち越さない
- Luna Maxをhard-coded discountではなくobserved headroomで自動昇格可能に変更。`aggressive` burn stateではxhighのimplementer/specialist/release auditをMaxへ昇格でき、burn加速時はxhigh/highへ自動downshift。recon/testはhighを維持し、actual Plus allowanceのauthorityはCodex `/status` / ChatGPT usage dashboardのまま維持
- `codex_plus_swarm.py` を追加し、既存adaptive role classifierから最小の高leverage Luna teamだけを選択。architect/reviewer/integration/acceptance/P0-P5はSol parentに残し、通常/headroom時は最大2 worker、conserve/criticalでは最大1 workerへ縮退。worker failureからreasoning effortへのsilent retryは引き続き禁止
- NVIDIA adaptive fleet profile `nvidia-balanced-2026-08` を追加し、Kimi K3 / DeepSeek V4 Pro / Nemotron 3.5 Lightning / Nemotron 3 Ultraをreasoning・specialist・coding・verification・review/release-auditへ役割分担
- `nvidia-request-profiles/v1` を追加し、Kimi / DeepSeek / Nemotronごとの `reasoning_effort`、bounded `reasoning_budget`、temperature、model別 `max_tokens` capをfleet実行時に自動適用。明示temperature overrideとpublic/private/secret境界は維持
- NVIDIA NIM hosted endpointをoptional worker providerとして追加。`NVIDIA_API_KEY` + `MADO_NVIDIA_MODEL` でOpenAI-compatible `/chat/completions` laneを利用可能にし、model IDを固定せず変動するhosted catalogをconfigurationとして扱う
- provider routerにdeterministic `fallback_candidates` を追加。候補は同一sensitivity policyを満たすrouteだけに限定し、public `--prefer-free` ではconfigured NVIDIA NIMをlogged-free Emperoより先に候補化
- NVIDIA hosted routeはpublicを既定とし、private payloadは `--allow-nvidia-private` / `MADO_ALLOW_NVIDIA_PRIVATE=1` の明示opt-inを要求、secret payloadは引き続きlocal-only
- `skill_registry.yaml` と `scripts/select_skills.py` を追加し、task domainと明示トリガーからオンデマンド専門Skillを決定的に推薦するrouting layerを追加
- 専門Skillは自動インストールせず、実際に利用可能なものだけをロードし、既存のfirst-party reference/vendor fallbackとMADO LOOP proof authorityを維持
- bounded task receiptに、実際に開いた・呼び出した専門Skillだけを `skills_used` として記録するprovenance contractを追加
- Web専用の `develop-web-game` / Three.js / Higgsfield系は `manual_only` とし、Godot中心のMADO LOOP 1.xが暗黙にruntime scopeを広げないよう固定

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