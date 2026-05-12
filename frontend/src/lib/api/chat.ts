import apiClient from './client'
import { getApiUrl } from '@/lib/config'
import {
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SendNotebookChatMessageRequest,
  NotebookChatMessage,
  BuildContextRequest,
  BuildContextResponse,
} from '@/lib/types/api'

/** Read the Bearer token from localStorage (same logic as apiClient interceptor). */
function getAuthToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    const raw = localStorage.getItem('auth-storage')
    if (!raw) return ''
    const { state } = JSON.parse(raw)
    return state?.token ?? ''
  } catch {
    return ''
  }
}

export const chatApi = {
  // Session management
  listSessions: async (notebookId: string) => {
    const response = await apiClient.get<NotebookChatSession[]>(
      `/chat/sessions`,
      { params: { notebook_id: notebookId } }
    )
    return response.data
  },

  createSession: async (data: CreateNotebookChatSessionRequest) => {
    const response = await apiClient.post<NotebookChatSession>(
      `/chat/sessions`,
      data
    )
    return response.data
  },

  getSession: async (sessionId: string) => {
    const response = await apiClient.get<NotebookChatSessionWithMessages>(
      `/chat/sessions/${sessionId}`
    )
    return response.data
  },

  updateSession: async (sessionId: string, data: UpdateNotebookChatSessionRequest) => {
    const response = await apiClient.put<NotebookChatSession>(
      `/chat/sessions/${sessionId}`,
      data
    )
    return response.data
  },

  deleteSession: async (sessionId: string) => {
    await apiClient.delete(`/chat/sessions/${sessionId}`)
  },

  // Messaging (synchronous, no streaming) — kept as fallback
  sendMessage: async (data: SendNotebookChatMessageRequest) => {
    const response = await apiClient.post<{
      session_id: string
      messages: NotebookChatMessage[]
    }>(
      `/chat/execute`,
      data
    )
    return response.data
  },

  /**
   * Stream a chat response token-by-token via SSE.
   * Calls onToken for each streamed token, onDone when the full response arrives,
   * and onError on failure.
   */
  streamMessage: async (
    data: SendNotebookChatMessageRequest,
    onToken: (token: string) => void,
    onDone: (messages: NotebookChatMessage[], addedSources: string[]) => void,
    onError: (error: string) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    const apiUrl = await getApiUrl()
    const token = getAuthToken()

    const response = await fetch(`${apiUrl}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
      signal,
    })

    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => `HTTP ${response.status}`)
      onError(text)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue
          try {
            const event = JSON.parse(jsonStr)
            if (event.type === 'token' && event.content) {
              onToken(event.content)
            } else if (event.type === 'done') {
              onDone(event.messages ?? [], event.added_sources ?? [])
            } else if (event.type === 'error') {
              onError(event.error ?? 'Unknown streaming error')
            }
          } catch {
            // malformed JSON line — skip
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  buildContext: async (data: BuildContextRequest) => {
    const response = await apiClient.post<BuildContextResponse>(
      `/chat/context`,
      data
    )
    return response.data
  },
}

export default chatApi
