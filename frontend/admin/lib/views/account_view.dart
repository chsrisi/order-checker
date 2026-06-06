import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class AccountView extends StatelessWidget {
  const AccountView({super.key});

  @override
  Widget build(BuildContext context) {
    final appState = context.watch<AppState>();
    final username = appState.username;

    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircleAvatar(
            radius: 40,
            child: Icon(Icons.person, size: 40),
          ),
          const SizedBox(height: 16),
          Text(
            username.isEmpty ? 'Admin' : username,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 32),
          FilledButton.icon(
            icon: const Icon(Icons.logout),
            label: const Text('Logout'),
            style: FilledButton.styleFrom(
              backgroundColor: Colors.red,
            ),
            onPressed: () => appState.handleLogout(),
          ),
        ],
      ),
    );
  }
}
