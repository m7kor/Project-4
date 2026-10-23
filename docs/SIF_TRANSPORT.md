# SIF startup, RPC transport and IOP reboot

The native EE library and the runtime's HLE entry points are two ways to register a command receiver. `dispatchSifCommand` first uses an explicitly registered HLE callback. If none exists, it reads the guest command-data pointer from `SIF_SYSREG_MAINADDR` and delivers a padded packet to that structure's receive buffer, then queues the SIF0 interrupt. The guest library selects and executes its own command handler; the runtime does not assume the stride of the guest's handler table.

The software-register names are distinct from the hardware register names:

| Software register | Meaning |
|---|---|
| `0x80000000` | IOP command receive address, SYSREG_SUBADDR |
| `0x80000001` | EE command-data pointer, SYSREG_MAINADDR |
| `0x80000002` | EE RPC initialization marker, SYSREG_RPCINIT |

For the HLE startup handshake, an EE-to-IOP DMA is recognized as an RPC initialization command only when it has the outgoing interrupt attribute, exactly 16 payload bytes, a matching packet size, no extra data, command `0x80000002`, option `1`, and a destination matching the guest's registered IOP command buffer. The reply is `SET_SREG(0, 1)`, a 24-byte command. The runtime does not set the guest software register directly or skip its polling loop.

The native receive path rejects absent, truncated, unsupported, and occupied buffers. It preserves the packet's extra-data-size field, normalizes the packet size and command ID, zero-pads the receive area, and catches interrupt dispatch failure. Ordinary DMA still copies into private IOP memory; an equal numeric EE address is not an alias.

Tests in `core/ps2xTest/src/ps2_sif_dma_tests.cpp` cover the request, delivery through a guest SIF0 receiver, malformed and unrelated packets, ordinary DMA, and protection of a pending packet.

## RPC wire gateway

The gateway recognizes 64-byte BIND and CALL commands. Packet size occupies the low byte of the first word; the upper 24 bits encode extra-data size. A four-byte CALL therefore carries `0x440`, not `0x40`. Requests retain their client, packet address and request identity in the RPC_END response. The guest's own callback completes its semaphore wait.

A known SID receives a descriptor and a distinct 16 KiB buffer in private IOP RAM. Unknown SIDs receive a null server. Synchronous calls (`rmode=1`) validate the input size, output range and IOP buffer destination, stage data through the existing IOP service interface, then return the actual provider output. Unhandled or deferred providers produce an explicit fault diagnostic rather than a fabricated successful response. Asynchronous calls and buffers larger than 16 KiB are not implemented by this gateway yet.

Physical IRX RPC output is accepted only after the guest handler reaches its return sentinel. Instruction-budget exhaustion or a yielded call does not complete the RPC. The capture tool classifies incomplete IOP calls and missing IOP imports as faults, alongside native transport failures. This closes an earlier diagnostic blind spot; old reports without such faults do not establish that the IOP layer was complete.

Before a physical CDVDFSV module registers its servers, the native CDVD backend provides CD init, disk-ready and a small SCMD subset (media mode, disk type, error and status). Once the real module registers a handler, it takes precedence. This subset is not complete CDVDFSV compatibility.

## Reboot image

The 104-byte IOP reset command supports the observed `rom0:UDNL <image path>` form. The parser checks ROMDIR names, table length, aligned file offsets, duplicate entries and file extents before changing IOP state. The current boot path resets the IOP subsystem and starts the image's FILEIO, CDVDFSV and LOADFILE modules as actual IRX code. Kernel libraries and CDVDMAN remain supplied by the runtime's IOP kernel and import layer. Other image layouts and a full firmware reboot are outside this path.

Only successful module entry results permit publishing BOOTEND. SMFLAG writes clear the requested bits; publishing readiness is deferred until the next read so that the guest's reset sequence cannot erase a synchronous reply. The stop-DMA syscall reflects the current synchronous transport, which has no outstanding copy on return.

The IOP kernel also implements mailbox creation, send, receive, poll, status and deletion, with FIFO/priority queues and blocked-thread wakeup. These are covered by queue and scheduling regressions in `ps2_iop_tests.cpp`. A diagnostic run traces at most 64 mailbox operations.

Local RE4 evidence: `artifacts/runs/20261005T154124Z-1ecaf82f` started all three IRX services and passed the reboot wait. `artifacts/runs/20261005T155051Z-a9c5c704` removed the missing mailbox-import warning but still waited after opening MODULES.DAT through FILEIO. Neither run produced a GS frame; file completion and game compatibility remain unverified.

The protocol and binary command-data layout were checked against the primary PS2SDK sources:

- [EE SIF command receiver and command-data layout](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/src/sifcmd.c)
- [SIF software registers and DMA attributes](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/include/sifdma.h)
- [IOP RPC startup reply](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/sifcmd/src/sifrpc.c)
- [RPC packet fields](https://github.com/ps2dev/ps2sdk/blob/master/common/include/sifrpc-common.h)
- [CDVDFSV RPC handlers](https://github.com/ps2dev/ps2sdk/blob/master/iop/cdvd/cdvdfsv/src/cdvdfsv.c)
- [EE IOP reset sequence](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/src/iopcontrol.c)
- [IOP mailbox interface](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/threadman/include/thmsgbx.h)

## Capturing boot evidence

```powershell
python -m ps2l run "game/Resident Evil 4 (USA)/SLUS_211.34" --timeout 30 --diagnostics
```

Each run has its own `diagnostics/state.jsonl` containing published EE snapshots, thread and semaphore state, and DMA/GS counters. PNG files are exported only when the GS exposes a latched presentation frame. `report.json` summarizes the snapshots and lists frame files, tolerating a truncated last snapshot after timeout. Neither host presentation ticks nor absence of logged faults certify playable output.
