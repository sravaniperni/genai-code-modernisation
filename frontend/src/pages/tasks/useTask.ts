import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { POLL_INTERVAL_MS } from '../../lib/config';
import { isTerminal } from '../../lib/states';

/** Task detail, re-polled while the task is still moving through its lifecycle. */
export function useTask(taskId: number, enabled = true) {
  return useQuery({
    queryKey: ['task', taskId],
    queryFn: () => api.tasks.get(taskId),
    enabled,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && !isTerminal(state) ? POLL_INTERVAL_MS : false;
    },
  });
}

export function useInvalidateTask(taskId: number) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
    void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };
}

export function useTaskActions(taskId: number) {
  const invalidate = useInvalidateTask(taskId);
  const cancel = useMutation({ mutationFn: () => api.tasks.cancel(taskId), onSuccess: invalidate });
  const restart = useMutation({
    mutationFn: () => api.tasks.restart(taskId),
    onSuccess: invalidate,
  });
  return { cancel, restart };
}
