/**
 * ChatPanel — full chat UI with message history and input form.
 * Uses useChatHistory and useSendMessage hooks.
 */
export function ChatPanel() {
  // TODO: implement with useChatHistory, useSendMessage, and MessageBubble
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg flex flex-col h-96">
      <div className="flex-1 p-4 overflow-y-auto">
        <p className="text-sm text-[#4A5568]">Ask the AI assistant anything about this event…</p>
      </div>
      <div className="border-t border-[#E2E8F0] p-3 flex gap-2">
        <input
          className="flex-1 border border-[#E2E8F0] rounded px-3 py-2 text-sm"
          placeholder="Type a message…"
        />
        <button className="bg-[#1E5A8D] text-white px-4 py-2 rounded text-sm">Send</button>
      </div>
    </div>
  )
}
