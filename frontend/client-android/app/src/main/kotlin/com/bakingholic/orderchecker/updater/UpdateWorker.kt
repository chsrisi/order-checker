package com.bakingholic.orderchecker.updater

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.bakingholic.orderchecker.OrderCheckerApp
import java.util.concurrent.TimeUnit

/** Periodic background check (every 15 min, WorkManager's minimum). Never fails the work. */
class UpdateWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        (applicationContext as OrderCheckerApp).graph.updates.check(minIntervalMillis = 60_000)
        return Result.success()
    }

    companion object {
        fun schedule(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "update-check",
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<UpdateWorker>(15, TimeUnit.MINUTES).build(),
            )
        }
    }
}
