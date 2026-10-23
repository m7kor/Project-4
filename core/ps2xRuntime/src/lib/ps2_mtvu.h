#pragma once

// Proposed MTVU interface: declarations only, not a running game feature.
// PS2X_MTVU does not activate this interface. The bounded transport exists
// separately in runtime/ps2_vif_work_queue.h; EE/context/interrupt barriers
// and lifecycle integration must be implemented before activation.
//
// The EE thread copies every VIF1 DMA payload and every EE-side GIF packet
// into one ordered queue; a worker runs the VIF1 interpreter (UNPACK, MPG,
// MSCAL -> VU1 -> XGKICK) and all GIF path submissions in that order, so GS
// packet order is unchanged. VIF1 DMA still completes at once, as the copied
// data sits in the queue like in the hardware FIFO.
//
// Everything the EE can observe of that work waits for the queue first
// (mtvuDrain): VIF1/GIF register reads and writes, VU1 memory access, and
// any GS call from the EE thread (GS::drainWorker / processGIFPacket hook).
// Only the producing (EE) thread drains; other threads (presentation) read
// GS state as before.
//
// The paragraphs above describe the intended ownership, not completed wiring.

#include <cstdint>

class PS2Memory;

bool mtvuEnabled();
// True on the worker thread: VIF1/GIF entry points run inline there.
bool mtvuOnWorker();
// Starts the worker for this memory (once); no-op when disabled.
void mtvuStart(PS2Memory *memory);
// Stops and joins the worker after finishing the queue.
void mtvuStop();
// EE thread: wait until every queued item has been processed.
void mtvuDrain();
// Queue items (EE thread, MTVU active).
void mtvuQueueVif1(const uint8_t *data, uint32_t sizeBytes);
void mtvuQueueGif(int pathId, const uint8_t *data, uint32_t sizeBytes, bool drainImmediately, bool path2DirectHl);
void mtvuQueueArbiterDrain();
// Queueing is in effect: enabled, worker running, caller is not the worker.
bool mtvuShouldQueue();
