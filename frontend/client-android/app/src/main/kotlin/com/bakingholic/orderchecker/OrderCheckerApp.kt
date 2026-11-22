package com.bakingholic.orderchecker

import android.app.Application

class OrderCheckerApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
    }
}
