from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.user_idle_processor import UserIdleProcessor


# Advanced handler with retry logic
async def handle_user_idle(processor: UserIdleProcessor, retry_count):
    if retry_count == 1:
        # First attempt - gentle reminder
        await processor.push_frame(TTSSpeakFrame("Are you still there?"))
        return True  # Continue monitoring
    else:
        # Third attempt - end conversation
        await processor.push_frame(TTSSpeakFrame("I'll leave you for now. Have a nice day!"))
        await processor.push_frame(EndFrame(), FrameDirection.UPSTREAM)
        return False  # Stop monitoring