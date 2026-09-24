# Device-family ownership and similarity map

This directory contains device-family semantic owners.

This README is a **review aid**, not independent protocol evidence. Its purpose is to record where two or more device families have a bounded common compatibility contract
or a related surface worth reviewing so a change to one family triggers an explicit review of the related families.

Similarity does **not** require shared implementation. Short duplication is preferred when it keeps family ownership independent.

## Ownership rules

- One device family owns its own register semantics, state decoding, pure encoding and family command intent/policy.
- A small family may use one module. A family with several meaningful semantic files may use a sub-package.
- Family semantic modules should not import sibling family semantic modules.
- Upper routers/orchestrators such as `state.py`, HA platforms and command dispatch may know multiple families.
- `state.py` resolves per-family room and per-channel light command owners (`room_command_owner`, `light_command_owner`) using the same
  family-neutral dispatch pattern as `state_decoder`/`definition_resolver`. `commands.py` invokes the resolved owner's intent/selection
  functions instead of branching on device type itself.
- Shared helpers are reserved for genuinely family-neutral primitives. A helper needing a concrete family/`device_type` branch is not family-neutral.
- When a relationship below changes, review the listed peers. A peer review may conclude **no change required**.
- When evidence diverges, update this table instead of forcing both families to keep identical code.

The ownership table below records the current implementation; no removed or superseded module retains a compatibility wrapper.

## Relationship classes

| Class | Meaning |
|---|---|
| Verified common contract | The listed semantic behavior is currently supported by evidence/tests for each listed family. Review peers when changing it. |
| Similar / cross-review | Implementations or layouts overlap, but differences already exist or full equivalence is not established. Keep family ownership separate. |
| Independent / no shared contract | The listed families are independent semantic owners with no shared protocol contract between them. Only the explicitly documented common-contract or cross-review rows in this table establish a relationship; a change to one independent family does not imply a corresponding change in another. |

## Current cross-family review relationships

| Families | Surface | Class | Review note |
|---|---|---|---|
| HCM, HVM | Bounded legacy packed-room decode and power/target edits | Verified common contract | Existing compatibility paths share R52-based words, bit0 power, current/target masks and the nonzero-R59 scale fallback. This records code/regression evidence, not physical qualification of every model. Each has its own short implementation. |
| HCM, HVM | Whole summary/profile/detail interpretation | Similar / cross-review | Room counts use R18 versus R21. Strict HVM observation accepts only R59=0/1 and is consumed by read-only Diagnostics, separate from legacy fallback. The coordinator's HVM decoder publishes this same observation with its climate-limit and provisional-control qualification; HVM climate min/max and HVM controls consume it directly. It does not establish HCM detail semantics or summary/detail equivalence. |
| HCM, HVM, HQM | Packed multi-room summary concepts | Similar / cross-review | HQM uses R23-based words, R16 count, fixed 0.5 scale and separate standalone behavior. Shared masks do not make the complete layout/units equivalent. Keep local records/bit helpers and review the affected surface in each family. |
| STM, SBM, SQM | Current per-channel switch compatibility path | Verified common contract | Existing routing and regressions use config as channel count, raw==1 state and channel-index register with 0/1 command. Three local implementations preserve that bounded contract; it does not qualify additional physical states/models. |
| AQM, PMM | Environmental measurement vs. power metering | Independent / no shared contract | Environmental measurements/metadata and power metering use independent registers, units and state; no semantic equivalence should be inferred between them. |
| CCM, RBM, STM, SBM, SQM, SDM | Outlet / cover / switch / dimmer command semantics | Independent / no shared contract | Outlet, cover, switch and dimmer semantics differ across these families. Only the explicit STM/SBM/SQM row above establishes a common current contract; the others remain fully independent. |
| ACM, BCM, HCM, HVM, HQM, TCM | Off-step climate target quantization policy | Similar / cross-review (policy only) | Each writer rounds an off-step request to the nearest step of its own grid, an exact midpoint selecting the higher temperature, through a short local Decimal helper. Grids and encodings stay family-owned: ACM/BCM 1.0 C; HCM/HVM the R59-selected 1.0 or 0.5 C room step; HQM rooms 0.5 C; HQM standalone and TCM 0.1 C. On-step values encode exactly. Review the other copies when this policy changes; it establishes no shared register semantics. |
| HCM, HVM, HQM | Heating semantics beyond the documented room/summary rows | Independent / no shared contract | Only the explicitly bounded common/cross-review rows above apply to these families; no further equivalence should be inferred beyond them. |
| AQM, BCM | `DeviceDefinition` infrastructure | Similar / cross-review (architecture only) | Shared definition/execution contracts require both consumers to be reviewed when infrastructure changes. Their register semantics, identity and qualification remain independent; a family-specific change alone does not require the other to change. |

## Current family ownership

Paths are relative to this directory. Packages contain multiple meaningful semantic owners, and their `__init__.py` files are docstring-only namespaces.

| Family | Canonical current owner |
|---|---|
| ACM | acm.py |
| AQM | aqm/: state.py, metadata.py, actions.py, definition.py, link.py, settings.py, trend.py, version.py, diagnostics.py |
| BCM | bcm/: state.py, definition.py, settings.py, schedule.py, diagnostics.py (capture-time interpretation) |
| CCM | ccm.py |
| RBM | rbm.py |
| STM | stm.py with local switch callables |
| SBM | sbm.py with local switch callables |
| SQM | sqm.py with local switch callables |
| SDM | sdm.py |
| PMM | pmm.py |
| HCM | hcm.py with local RoomState/packed helpers |
| HQM | hqm.py with local RoomState/packed helpers |
| HVM | hvm/: summary.py (legacy room summary), observation.py (strict/pure decode, published observation, single-room climate-limit and control-context policy), controls.py (provisional single-register command selection), schedule.py (pure codecs), diagnostics.py (capture-time interpretation) |
| TCM | tcm.py |
| RCM | Identifier-only; no active semantic owner |

`state.py` is the upper router/snapshot composition owner: it binds each family's decoder/definition/command-owner resolution and owns no family
semantics itself. `definition.py` is neutral definition/execution infrastructure (`DeviceDefinition`, `Feature`, `CommandExecution`) shared only by
families that opt into it (currently AQM and BCM); `numeric.py` retains the three neutral arithmetic primitives. Neither infrastructure use nor
numeric reuse implies family-semantic equivalence. Runtime execution, commands and HA platforms retain their existing upper responsibilities. No
family module imports another family's semantic module.

## Command ownership

Family-specific command sequencing, value selection and per-family command routing are owned by the family module, not by the shared
runtime. `commands.py` (the ConfigEntry's command transaction owner) is limited to transaction admission/serialization, quiesce/resume/shutdown
lifecycle, cancellation-safe I/O draining, invoking the physical writes/waits a family policy requests, coordinator refresh, and generic execution
of whichever device-owned policy the family/feature resolves to. For example: ACM/TCM own their own mode/power sequencing; CCM owns its
single-attempt/failure-propagation policy; SDM owns its on-command-versus-explicit-level selection; HCM/HVM/HQM own their own room register/state/
command intent, resolved through `state.py`'s `room_command_owner`; STM/SBM/SQM own their own switch intent, resolved through `light_command_owner`.
HVM provisional controls pass a family-owned selector to the neutral `async_snapshot_write`, which writes the one selected intent and refreshes.

## Diagnostics ownership

HVM, BCM and AQM Diagnostics reuse common collection/export/lifecycle. Each family owns only its own capture-time projection and existing
version/read gates; no family imports a sibling family's diagnostics helpers. AQM owns the explicit R55-R57 linked-MAC range and decoded aliases
applied by the common export path. Their similar JSON shape establishes no shared register or schedule semantics between families.

## HA climate/heating platform routing

`climate.py::async_setup_entry()` performs family routing with separate HCM, HVM and HQM branches, then ACM, BCM and TCM. HCM owns
`Hcm300`/`HcmVirtualThermostat`; HVM owns `Hvm300`/`HvmVirtualThermostat`; HQM owns `Hqm300`/`HqmVirtualThermostat`/`HqmStandaloneThermostat`.
Virtual thermostat classes directly inherit the family-neutral HA projection boundary and `ClimateEntity`, never a sibling-family thermostat.
Entity groups do not select sibling families; short local projection copies preserve each family's own state, identity, services and packet
contracts. A value-identical `ROOM_SUPPORTED_FEATURES` constant is neutral HA metadata, not a semantic owner. HVM's single-room dynamic/fallback
climate bounds are derived from the same normal coordinator snapshot as its other state; platform routing does not change semantic packages or
commands. The bounded similarity rows above are cross-review information; they do not require shared implementation or moving HA entities into
device packages.

## Change-review procedure

When changing a family semantic module:

1. Identify the changed semantic surface.
2. Check this README for related families.
3. Review the peer family's evidence/tests for that surface.
4. Either:
   - make the corresponding peer change because the verified contract is still shared;
   - make no peer code change and record that the contracts remain different; or
   - update this README because the relationship has converged/diverged.
5. Do not introduce a shared family helper solely to keep two short implementations synchronized.

The README should evolve with evidence. It should never be used to promote a merely similar implementation into a qualified protocol contract.
