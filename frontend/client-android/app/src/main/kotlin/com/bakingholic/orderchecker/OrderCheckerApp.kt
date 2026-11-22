package com.bakingholic.orderchecker

import android.app.Application
import com.bakingholic.orderchecker.updater.UpdateWorker

class OrderCheckerApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        UpdateWorker.schedule(this)
    }
}
