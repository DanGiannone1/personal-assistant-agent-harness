targetScope = 'resourceGroup'

param environmentName string
param acrServer string
@minLength(40)
@maxLength(40)
param imageTag string
param frontendAppName string
param apiAppName string
param runtimeAppName string
param frontendIdentityId string
param apiIdentityId string
param runtimeIdentityId string
param tenantId string
param apiClientId string
param runtimeClientId string
param frontendUrl string
param runtimeFqdn string
param cosmosAccountName string
param storageAccountName string
param azureOpenAiEndpoint string
param azureOpenAiDeployment string
param databaseName string
@allowed([
  'entra'
  'demo'
])
param identityMode string = 'entra'
@secure()
param demoPassword string = ''

var containerName = 'appstate'
var artifactContainer = 'engagement-artifacts'
var cosmosEndpoint = 'https://${cosmosAccountName}.documents.azure.com:443/'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource frontend 'Microsoft.App/containerApps@2024-03-01' = {
  name: frontendAppName
  location: resourceGroup().location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${frontendIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: acrServer, identity: frontendIdentityId }]
      ingress: { external: true, targetPort: 3000, transport: 'auto' }
    }
    template: {
      scale: { minReplicas: 0, maxReplicas: 1 }
      containers: [{ name: 'frontend', image: '${acrServer}/csa-workbench-frontend:${imageTag}', resources: { cpu: json('0.25'), memory: '0.5Gi' } }]
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiAppName
  location: resourceGroup().location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: identityMode == 'demo' ? [{ name: 'demo-password', value: demoPassword }] : []
      registries: [{ server: acrServer, identity: apiIdentityId }]
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
    }
    template: {
      scale: { minReplicas: 0, maxReplicas: 1 }
      containers: [{
        name: 'api'
        image: '${acrServer}/csa-workbench-api:${imageTag}'
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: concat([
          { name: 'AZURE_CLIENT_ID', value: reference(apiIdentityId, '2023-01-31').clientId }
          { name: 'IDENTITY_MODE', value: identityMode }
          { name: 'ENTRA_TENANT_ID', value: tenantId }
          { name: 'ENTRA_API_CLIENT_ID', value: apiClientId }
          { name: 'ENTRA_ALLOWED_AUDIENCES', value: 'api://${apiClientId}' }
          { name: 'FRONTEND_URL', value: frontendUrl }
          { name: 'POOL_MANAGEMENT_ENDPOINT', value: 'https://${runtimeFqdn}' }
          { name: 'POOL_AUTH_AUDIENCE', value: 'api://${runtimeClientId}' }
          { name: 'FORWARD_AZURE_OPENAI_TOKEN', value: 'false' }
          { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
          { name: 'COSMOS_DATABASE', value: databaseName }
          { name: 'COSMOS_CONTAINER', value: containerName }
          { name: 'ARTIFACTS_ACCOUNT', value: storageAccountName }
          { name: 'ARTIFACTS_CONTAINER', value: artifactContainer }
        ], identityMode == 'demo' ? [{ name: 'DEMO_PASSWORD', secretRef: 'demo-password' }] : [])
      }]
    }
  }
}

resource runtime 'Microsoft.App/containerApps@2024-03-01' = {
  name: runtimeAppName
  location: resourceGroup().location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runtimeIdentityId}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: { activeRevisionsMode: 'Single', registries: [{ server: acrServer, identity: runtimeIdentityId }], ingress: { external: false, targetPort: 8080, transport: 'auto' } }
    template: {
      scale: { minReplicas: 0, maxReplicas: 1 }
      containers: [{
        name: 'runtime'
        image: '${acrServer}/csa-workbench-runtime:${imageTag}'
        resources: { cpu: json('1'), memory: '2Gi' }
        env: [
          { name: 'AZURE_CLIENT_ID', value: reference(runtimeIdentityId, '2023-01-31').clientId }
          { name: 'WORKLOAD_AUTH_MODE', value: 'entra' }
          { name: 'WORKLOAD_ENTRA_TENANT_ID', value: tenantId }
          { name: 'WORKLOAD_ENTRA_AUDIENCE', value: runtimeClientId }
          { name: 'WORKLOAD_ENTRA_CALLER_OBJECT_ID', value: reference(apiIdentityId, '2023-01-31').principalId }
          { name: 'WORKLOAD_ENTRA_REQUIRED_ROLE', value: 'invoke' }
          { name: 'AZURE_ENDPOINT', value: azureOpenAiEndpoint }
          { name: 'AZURE_DEPLOYMENT', value: azureOpenAiDeployment }
          { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
          { name: 'COSMOS_DATABASE', value: databaseName }
          { name: 'COSMOS_CONTAINER', value: containerName }
        ]
      }]
    }
  }
}

output frontendUrl string = 'https://${frontend.properties.configuration.ingress.fqdn}'
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output runtimeFqdn string = runtime.properties.configuration.ingress.fqdn
