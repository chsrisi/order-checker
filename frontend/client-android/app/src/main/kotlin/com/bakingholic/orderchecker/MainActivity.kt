package com.bakingholic.orderchecker

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.bakingholic.orderchecker.core.AppInfo

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val info = AppInfo(BuildConfig.VERSION_CODE, BuildConfig.VERSION_NAME)
        setContent { MaterialTheme { Shell(info) } }
    }
}

@Composable
private fun Shell(info: AppInfo) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.padding(24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Order Checker", style = MaterialTheme.typography.headlineMedium)
            Text(info.label, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Preview
@Composable
private fun ShellPreview() {
    MaterialTheme { Shell(AppInfo(1, "2.0.0")) }
}
